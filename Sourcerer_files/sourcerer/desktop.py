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
import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from werkzeug.serving import make_server

from . import config, db, net, previews, server, sync

log = logging.getLogger("sourcerer")
RUNNING = config.USERDATA / "running.json"
IDLE_MINUTES = 15


def _logging():
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file = logging.handlers.RotatingFileHandler(
        config.LOG_DIR / "sourcerer.log", maxBytes=1 << 20, backupCount=3, encoding="utf-8")
    file.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("  %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file)
    root.addHandler(console)
    # One line per request drowns everything else; errors still get through.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


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


def window_check():
    """The child of `_window_ok`: exit 0 only if Qt can open a window here."""
    from qtpy.QtWidgets import QApplication
    from qtpy.QtWebEngineWidgets import QWebEngineView  # noqa: F401 -- Qt wants it before the application
    QApplication([])
    return 0


def _window_ok():
    """Whether pywebview can open a window. Only Linux needs asking: its Qt does not raise when it
    cannot start (no display, no xcb-cursor library) -- it aborts the process, server included.
    So a child tries first, and the browser is the answer when it dies."""
    if not sys.platform.startswith("linux") or importlib.util.find_spec("gi"):
        return True                                         # GTK from the system, as ever
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    cmd = [sys.executable, "--window-check"] if config.FROZEN else \
        [sys.executable, "-c", "import sys; from sourcerer import desktop; sys.exit(desktop.window_check())"]
    try:
        done = subprocess.run(cmd, cwd=None if config.FROZEN else str(config.ROOT),
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        log.info("Window check did not run: %s", e)
        return False
    if done.returncode:
        lines = (done.stderr or "").strip().splitlines()
        log.info("Qt cannot open a window here (%s)", lines[-1] if lines else "code %s" % done.returncode)
        return False
    if os.geteuid() == 0:                                   # Chromium refuses to start as root otherwise
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")
    return True


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
    sync.name_avatars()
    _after_update()
    net.configure(per_host=db.setting_int("per_host", 1, 8), pace_ms=db.setting_int("pace_ms", 0, 5000))
    sync.scheduler()
    previews.start()
    httpd = make_server("127.0.0.1", args.port, server.app, threaded=True)
    url = "http://127.0.0.1:%d/" % httpd.server_port
    threading.Thread(target=httpd.serve_forever, daemon=True, name="server").start()
    log.info("Sourcerer v%s at %s", config.VERSION, url)
    server.URL = url
    _announce(httpd.server_port)
    try:
        if not (args.browser or args.no_open):
            try:
                if not _window_ok():
                    raise RuntimeError("no Qt or GTK window possible")
                import webview
                server.WINDOW = webview.create_window(
                    "Sourcerer v%s" % config.VERSION, url, width=1280, height=860, min_size=(760, 520))
                webview.start()
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
