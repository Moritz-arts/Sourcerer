"""main(): logging, database, the server in a thread, then the window -- or the browser.

The window is pywebview, as in TrackImage. Where it cannot open (the package
did not install, no WebView2 on Windows, no GTK/Qt bindings on Linux), the
same page opens in the default browser.

launch.py starts this detached from its console (SOURCERER_DETACHED) and waits
for Userdata/running.json, which says that Sourcerer serves and on which port.
In the browser there is then no console to close: the page's Quit button ends
Sourcerer, and so does a page that has not been open for IDLE_MINUTES.
"""
import argparse
import importlib.util
import inspect
import json
import logging
import logging.handlers
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from werkzeug.serving import make_server

from . import config, db, follows, net, server, sync

log = logging.getLogger("sourcerer")
RUNNING = config.USERDATA / "running.json"
IDLE_MINUTES = 15


class _Short(logging.Formatter):
    """`2026-10-20 18:30:01 WARNING follows | X: ...` -- the module without its package, the level one word wide."""
    def format(self, record):
        record.short = record.name.replace("sourcerer.sources.", "").replace("sourcerer.", "")
        return super().format(record)


def _logging():
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    file = logging.handlers.RotatingFileHandler(
        config.LOG_DIR / "sourcerer.log", maxBytes=1 << 20, backupCount=3, encoding="utf-8")
    file.setFormatter(_Short("%(asctime)s %(levelname)-7s %(short)s | %(message)s"))
    # stderr is Logs/console.log when Sourcerer runs without a console: only what needs a look is written there (the rest
    # is the program log, and a second copy of it made the two files read alike). A console somebody watches gets it all.
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("  %(message)s"))
    console.setLevel(logging.INFO if sys.stderr is not None and sys.stderr.isatty() else logging.WARNING)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file)
    root.addHandler(console)
    # One line per request drowns everything else; errors still get through.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    # Every start opens a block in both files, so a line is found under the start it belongs to.
    head = "Sourcerer v%s started: %s, Python %s%s" % (config.VERSION, platform.platform(), platform.python_version(),
                                                      ", standalone build" if config.FROZEN else "")
    logging.getLogger("sourcerer").info("=== %s ===", head)
    if sys.stderr is not None and not sys.stderr.isatty():
        print("\n=== %s ===\n(This file is the program's raw output: warnings and crashes. What Sourcerer did, with the time, "
              "is in sourcerer.log.)" % head, file=sys.stderr, flush=True)
    try:        # which file holds what, where somebody looks for it
        (config.LOG_DIR / "README.txt").write_text(
            "Sourcerer's log files\n\n" + "\n\n".join("%s -- %s\n%s" % (name, title, about) for name, title, about in config.LOG_FILES) +
            "\n\nSourcerer shows them too: Activity > Log files.\nA line starts with its time; WARNING and ERROR are the ones to look at.\n",
            encoding="utf-8")
    except OSError:
        pass


def _after_update():
    """The update helper's last run, once, as a line in the activity log -- also
    when Sourcerer was started by hand afterwards, because the helper could not."""
    os.environ.pop("SOURCERER_AFTER_UPDATE", None)
    try:
        lines = (config.LOG_DIR / "update.log").read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    # HELPER opens its block with the first line, the Windows installer's script (updater.SETUP_CMD) with the second.
    starts = [i for i, line in enumerate(lines)
              if line.endswith(("  waiting for Sourcerer to close", "  update by Setup"))]
    if not starts:
        return
    block = lines[starts[-1]:]
    stamp = block[0][:19]
    if stamp <= (db.get_setting("update_seen") or ""):
        return
    db.set_setting("update_seen", stamp)
    text = "\n".join(block)
    if "  restarting" in text:
        sync.event("info", "Restarted")
    elif "new version in place" in text:
        sync.event("done", "Updated to v%s" % config.VERSION)
    else:
        why = next((line.split("  ", 1)[-1] for line in block
                    if any(w in line for w in ("failed", "could not", "did not", "broke", "RESTORE"))),
                   block[-1].split("  ", 1)[-1])
        sync.event("error", "The update did not go through: %s -- details in Settings > Updates" % why)


def _announce(port):
    RUNNING.write_text(json.dumps({"app": "sourcerer", "pid": os.getpid(), "port": port,
                                   "version": config.VERSION, "started": time.time()}),
                       encoding="utf-8")


def _forget():
    try:
        if json.loads(RUNNING.read_text(encoding="utf-8")).get("pid") == os.getpid():
            RUNNING.unlink()
    except (OSError, ValueError):
        pass


def _running(focus=False):
    """Whether a Sourcerer answers on the port running.json names; with focus, asks it to come forward.
    No proxy: a system proxy would swallow 127.0.0.1."""
    try:
        port = json.loads(RUNNING.read_text(encoding="utf-8"))["port"]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = "http://127.0.0.1:%s" % port
        with opener.open(base + "/api/ping", timeout=2) as r:
            if json.loads(r.read().decode("utf-8")).get("app") != "sourcerer":
                return False
        if focus:
            opener.open(urllib.request.Request(base + "/api/focus", data=b""), timeout=2).close()
        return True
    except (OSError, ValueError, KeyError):
        return False


_ICONED = set()


def _window_icon(hwnd):
    """Windows: the brand icon on the window and its taskbar button. A start from source runs under pythonw.exe, whose icon is
    Python's; an installed Sourcerer.exe carries its own. Best effort -- the icon is not worth a failed start. Once per window
    (_custom_frame runs again at every page load while the native bar stays: each pass would load, and leak, two icons), and the big
    icon is asked at 64 px, not at SM_CXICON's 32: the taskbar scales it down on a 125-200 % screen instead of up."""
    key = getattr(hwnd, "value", hwnd)
    if key in _ICONED:
        return
    _ICONED.add(key)
    try:
        import ctypes
        from ctypes import wintypes
        user32 = server.own_user32()
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        path = str(config.STATIC / "favicon.ico")
        # IMAGE_ICON = 1, LR_LOADFROMFILE = 0x10; WM_SETICON = 0x80 (ICON_SMALL 0 / ICON_BIG 1); SM_CXSMICON 49
        for which, size in ((1, 64), (0, user32.GetSystemMetrics(49) or 16)):
            icon = user32.LoadImageW(None, path, 1, size, size, 0x10)
            if icon:                                     # (kept for the window's life; the icon it had before is the process's, not ours to free)
                user32.SendMessageW(hwnd, 0x80, which, icon)
    except Exception as e:
        log.info("window icon not set: %s", e)


def _custom_frame(window):
    """Windows: take the title bar off, so the page's own bar is the top of the window and draws the
    buttons (minimize, maximize, close). The resize border stays: only WS_CAPTION goes, and the style is
    read back -- the page draws its buttons only when the bar really is gone (server.CUSTOM_FRAME), so
    anything that goes wrong leaves the native bar and nothing is doubled. What is done after that (a
    window that fits the screen, the maximized bounds) can fail on its own: the bar is gone by then."""
    if server.CUSTOM_FRAME:
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = server._win32()["user32"]    # not ctypes.windll.user32: its argtypes would break pywebview's own SetWindowPos (a window move)
        hwnd = wintypes.HWND(int(window.native.Handle.ToInt64()))
        server.HWND[0] = hwnd
        _window_icon(hwnd)
        GWL_STYLE, WS_CAPTION, WS_THICKFRAME, WS_MINIMIZEBOX, WS_MAXIMIZEBOX = -16, 0x00C00000, 0x00040000, 0x00020000, 0x00010000
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE, (style & ~WS_CAPTION) | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        # SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020)
        server.CUSTOM_FRAME = not (user32.GetWindowLongW(hwnd, GWL_STYLE) & WS_CAPTION)
        log.info("window frame: %s", "the page's own bar" if server.CUSTOM_FRAME else "native (could not be removed)")
    except Exception as e:
        server.CUSTOM_FRAME = False
        log.info("window frame stays native: %s", e)
        return
    for step in (server.fit_to_screen, lambda: server.keep_taskbar(window), lambda: server.follow_monitor(window)):
        try:
            step()
        except Exception as e:
            log.info("window set-up step failed: %s", e)


# The library a minimal Linux lacks, as the loader names it -> the Debian/Ubuntu package that has it. Qt stops at the first one it
# cannot find, so the user learns them one start at a time unless README lists them all.
_QT_LIBS = {"libEGL.so.1": "libegl1", "libxkbcommon-x11.so.0": "libxkbcommon-x11-0", "libxcb-cursor.so.0": "libxcb-cursor0",
            "libxcb-icccm.so.4": "libxcb-icccm4", "libxcb-image.so.0": "libxcb-image0", "libxcb-keysyms.so.1": "libxcb-keysyms1",
            "libxcb-render-util.so.0": "libxcb-render-util0", "libxcb-xkb.so.1": "libxcb-xkb1", "libxcb-util.so.1": "libxcb-util1"}


def _webview2_problem():
    """Windows: why pywebview would not use WebView2, or None. pywebview does not fail without the runtime -- it opens the page in
    MSHTML, Internet Explorer's engine, which cannot run it and which the browser fallback below never gets to replace. This is the
    look pywebview itself makes (winforms._is_chromium): .NET Framework 4.6.2 and a WebView2 version in the registry."""
    try:
        import platform as _platform
        import winreg
        import webview
        if webview.settings.get("WEBVIEW2_RUNTIME_PATH"):
            return None
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as net:
            if winreg.QueryValueEx(net, "Release")[0] < 394802:
                return "it needs .NET Framework 4.6.2 or newer"
        for guid in ("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",
                     "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}", "{65C35B14-6C1D-4122-AC46-7148CC9D6497}"):     # runtime, beta, dev, canary
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                wow = "" if _platform.machine() == "x86" or hive == winreg.HKEY_CURRENT_USER else "WOW6432Node\\"
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\%sMicrosoft\EdgeUpdate\Clients\%s" % (wow, guid)) as key:
                        if int(str(winreg.QueryValueEx(key, "pv")[0]).split(".")[0]) >= 86:
                            return None
                except (OSError, ValueError):
                    pass
        return "the Microsoft Edge WebView2 Runtime is not installed (free from Microsoft; Windows 11 has it)"
    except OSError:
        return "it needs .NET Framework 4.6.2 or newer"
    except Exception:
        return None                                            # cannot be told: let pywebview try


def _window_problem():
    """None when pywebview can open a window here, else (why, tell): a sentence for the log, and whether the user can do something
    about it (then the activity log says so too -- a browser tab that opens without a word looks like a program that has no window).
    Linux: Qt does not raise when it cannot start (no display, a library missing) -- it aborts the process, server included -- so a
    child tries first, and the browser is the answer when it dies."""
    if os.name == "nt":
        why = _webview2_problem()
        return (why, True) if why else None
    if not sys.platform.startswith("linux") or importlib.util.find_spec("gi"):
        return None                                             # GTK from the system, as ever
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "no display (DISPLAY and WAYLAND_DISPLAY are not set)", False
    cmd = [sys.executable, "--window-check"] if config.FROZEN else \
        [sys.executable, "-c", "import sys; from sourcerer import window_probe; sys.exit(window_probe.main())"]

    def probe(debug):
        # (QT_DEBUG_PLUGINS makes Qt name the library a platform plugin lacks -- and fills stderr with what it is not interested in)
        return subprocess.run(cmd, cwd=None if config.FROZEN else str(config.ROOT), capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, QT_DEBUG_PLUGINS="1") if debug else None)
    try:
        done = probe(True)
        if done.returncode:
            lib = re.search(r"(lib[\w.+-]+\.so[\w.]*): cannot open shared object file", done.stderr or "")
            if lib:
                package = _QT_LIBS.get(lib.group(1))
                return "Qt needs %s%s -- README lists everything the Linux window needs" % (
                    lib.group(1), " (Debian/Ubuntu: %s)" % package if package else ""), True
            lines = [line for line in (done.stderr or "").strip().splitlines() if line.strip()]
            if not (lines and re.match(r"\w*(Error|Exception)\b", lines[-1])):
                done = probe(False)             # Qt's own words, without the debug noise (a Python error, like no Qt in this build, needs no second run)
    except (OSError, subprocess.SubprocessError) as e:
        return "the window check did not run: %s" % e, False
    if done.returncode:
        lines = [line for line in (done.stderr or "").strip().splitlines() if line.strip()]
        return "Qt cannot open a window here (%s)" % (lines[-1] if lines else "code %s" % done.returncode), False
    if os.geteuid() == 0:                                   # Chromium refuses to start as root otherwise
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")
    return None


def _serve_until_idle():
    """Browser mode without a console: run while a page is open, or a sync is."""
    while True:
        time.sleep(30)
        if os.environ.get("SOURCERER_DETACHED") and not sync.status()["running"] and \
                time.monotonic() - server.LAST_SEEN[0] > IDLE_MINUTES * 60:
            log.info("No page open for %d minutes -- Sourcerer stops.", IDLE_MINUTES)
            return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sourcerer")
    parser.add_argument("--browser", action="store_true", help="open in the browser, not a window")
    parser.add_argument("--no-open", action="store_true", help="open nothing; just serve")
    parser.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: any free)")
    parser.add_argument("--restart", action="store_true", help="exe: wait until the running Sourcerer is gone")
    args = parser.parse_args(argv)

    if config.FROZEN:                       # launch.py does both for the launchers
        for _ in range(100 if args.restart else 0):
            if not _running():
                break
            time.sleep(0.3)
        if _running(focus=True):
            return 0
    _logging()
    db.init()
    shutil.rmtree(config.UPDATE_DIR, ignore_errors=True)    # an update that never got installed
    # Up to v0.5 the cards' pictures were copied into Userdata/Thumbs; they are
    # made in memory now, and the copies are only clutter.
    shutil.rmtree(config.USERDATA / "Thumbs", ignore_errors=True)
    _after_update()
    net.configure(per_host=db.setting_int("per_host", 1, 32), pace_ms=db.setting_int("pace_ms", 0, 5000))
    sync.scheduler()
    follows.start()
    httpd = make_server("127.0.0.1", args.port, server.app, threaded=True)
    url = "http://127.0.0.1:%d/" % httpd.server_port
    threading.Thread(target=httpd.serve_forever, daemon=True, name="server").start()
    log.info("Sourcerer v%s at %s", config.VERSION, url)
    server.URL = url
    _announce(httpd.server_port)
    try:
        if not (args.browser or args.no_open):
            try:
                problem = _window_problem()
                if problem:
                    if problem[1]:
                        sync.event("warn", "No app window: %s. Sourcerer opens in your browser instead." % problem[0])
                    raise RuntimeError(problem[0])
                import webview
                if os.name == "nt":
                    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True     # a drag starts on the bar itself, not on its buttons
                server.WINDOW = webview.create_window(
                    "Sourcerer v%s" % config.VERSION, url, width=1280, height=860, min_size=(760, 520))
                if os.name == "nt":
                    server.WINDOW.events.shown += lambda: _custom_frame(server.WINDOW)
                    server.WINDOW.events.loaded += lambda: _custom_frame(server.WINDOW)       # once more if `shown` came too early
                # The icon argument is Qt's and GTK's (a PNG). On Windows pywebview builds a .NET Icon from it and a PNG is no icon: the
                # restarted Sourcerer of the smoke test came up, logged its port and was gone (v0.55's first build); Windows gets its icon
                # from the exe and from _window_icon.
                options = {}
                if sys.platform.startswith("linux"):
                    parameters = inspect.signature(webview.start).parameters
                    if "icon" in parameters:
                        options["icon"] = str(config.STATIC / "icon.png")
                    if "gui" in parameters and not importlib.util.find_spec("gi"):
                        options["gui"] = "qt"       # without it pywebview tries GTK first and every start logs "GTK cannot be loaded" with a traceback
                webview.start(**options)
                return 0                                      # the window was closed
            except Exception as e:
                server.WINDOW = None
                log.info("No app window (%s) -- opening the browser instead.", e)
        if not args.no_open:
            webbrowser.open(url)
        if not os.environ.get("SOURCERER_DETACHED"):
            print("\n  Sourcerer runs at %s -- close this window to stop it.\n" % url, flush=True)
        return _serve_until_idle()
    except KeyboardInterrupt:
        return 0
    finally:
        _forget()
