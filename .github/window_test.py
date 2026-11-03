"""Drives Sourcerer's real window on a Windows runner with the real mouse and says what the window did.

    python .github/window_test.py [path\\to\\Sourcerer.exe]

Run by .github/workflows/window-test.yml (Windows only): starts Sourcerer -- from source, or the frozen exe it is given --, waits
until the page is drawn (the page is asked through WebView2's debugging port), then presses the page's own bar with injected mouse
events and reads where the window is: the bar moves the window, a drag to the screen's edge docks it (half, quarter, maximized), a
drag out of a docked window gives it its size back, a double-click maximizes, and all of it works under a dialog.
A failing check starts with FAIL; WINDOW_TEST_STRICT=1 makes the exit code say so. The logs of the run are kept in ./window-test.
"""
import ctypes
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "window-test"
CDP_PORT = 9333
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDPIAware()
SCREEN = (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
FAILS = []
BASE = (60, 40, 860, 600)                      # a normal window of 800x560, which is not the size of anything the tests dock it to


def say(text=""):
    print(text, flush=True)


def check(ok, text):
    say(("ok    " if ok else "FAIL  ") + text)
    if not ok:
        FAILS.append(text)


def http(port, path, body=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request("http://127.0.0.1:%s%s" % (port, path),
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"} if body is not None else {})
    with opener.open(request, timeout=10) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


class Page:
    """The page inside the window, through the Chrome DevTools protocol WebView2 offers on a debugging port."""

    def __init__(self):
        import websocket
        targets = json.loads(urllib.request.build_opener(urllib.request.ProxyHandler({}))
                             .open("http://127.0.0.1:%d/json" % CDP_PORT, timeout=5).read().decode("utf-8"))
        page = next(t for t in targets if t.get("type") == "page" and "127.0.0.1" in t.get("url", ""))
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=15, suppress_origin=True)
        self.n = 0

    def run(self, expression):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": "Runtime.evaluate",
                                 "params": {"expression": expression, "returnByValue": True}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.n:
                return message.get("result", {}).get("result", {}).get("value")


# ---- the window and the mouse
def rect_of(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def client_origin(hwnd):
    p = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y


def work_area():
    r = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)       # SPI_GETWORKAREA
    return (r.left, r.top, r.right, r.bottom)


def zoomed(hwnd):
    return bool(user32.IsZoomed(hwnd))


def find_window():
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.startswith("Sourcerer v") and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    user32.EnumWindows(each, 0)
    return found[0] if found else None


def point(x, y):
    user32.mouse_event(0x0001 | 0x8000, int(x * 65535 / (SCREEN[0] - 1)), int(y * 65535 / (SCREEN[1] - 1)), 0, 0)   # MOVE | ABSOLUTE


def down():
    user32.mouse_event(0x0002, 0, 0, 0, 0)


def up():
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def drag(start, end, steps=24, pause=0.02, hold=0.25):
    """Press at `start`, move to `end` in steps, release."""
    point(*start)
    time.sleep(0.3)
    down()
    time.sleep(hold)
    for i in range(1, steps + 1):
        point(start[0] + (end[0] - start[0]) * i / steps, start[1] + (end[1] - start[1]) * i / steps)
        time.sleep(pause)
    time.sleep(0.25)
    up()
    time.sleep(0.9)


def bar_point(hwnd, dx=31, dy=26):
    """The brand mark in the page's bar (css px from the client origin; the runner is 100 %)."""
    cx, cy = client_origin(hwnd)
    return cx + dx, cy + dy


def normal(hwnd, page=None):
    """The window as every test starts: not maximized, 800x560 at a fixed place."""
    if zoomed(hwnd):
        user32.ShowWindow(hwnd, 9)                             # SW_RESTORE
        time.sleep(0.4)
    user32.SetWindowPos(hwnd, None, BASE[0], BASE[1], BASE[2] - BASE[0], BASE[3] - BASE[1], 0x0004 | 0x0010)
    time.sleep(0.8)                                            # (the page hears of the new size and asks what became of the window)


def flags(page, hwnd):
    return "page: maxed=%s snapped=%s" % (page.run("S.maxed"), page.run("S.snapped")) if page else ""


def events(page):
    return page.run("JSON.stringify(window.__bar.splice(0))") if page else ""


def main():
    OUT.mkdir(exist_ok=True)
    exe = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    env = dict(os.environ, PYTHONUNBUFFERED="1", WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=%d" % CDP_PORT)
    if exe:
        data, cmd, cwd = exe.parent / "Userdata", [str(exe)], str(exe.parent)
    else:
        data, cmd, cwd = ROOT / "Sourcerer_files" / "Userdata", [sys.executable, str(ROOT / "Sourcerer_files" / "app.py")], str(ROOT)
        env["SOURCERER_DETACHED"] = "1"
    app = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=open(OUT / "app.out", "w"), stderr=subprocess.STDOUT)
    try:
        run(data)
    finally:
        app.kill()
        for name in ("sourcerer.log", "console.log"):
            try:
                (OUT / name).write_text((data / "Logs" / name).read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            except OSError:
                pass
    say("")
    say("%d check(s) failed: %s" % (len(FAILS), "; ".join(FAILS)) if FAILS else "all window checks passed")
    return 1 if FAILS and os.environ.get("WINDOW_TEST_STRICT") else 0


def run(data):
    started = time.time()
    port = None
    for _ in range(240):
        try:
            port = json.loads((data / "running.json").read_text(encoding="utf-8"))["port"]
            http(port, "/api/ping")
            break
        except (OSError, ValueError, KeyError):
            port = None
            time.sleep(0.5)
    check(port is not None, "Sourcerer serves (%.1f s)" % (time.time() - started))
    if port is None:
        return
    hwnd = None
    for _ in range(240):
        hwnd = find_window()
        if hwnd:
            break
        time.sleep(0.5)
    check(hwnd is not None, "the app window opens (%.1f s)" % (time.time() - started))
    if not hwnd:
        return
    page = None
    for _ in range(180):                                       # until the page is drawn and has dressed the bar
        try:
            page = page or Page()
            if page.run("typeof S !== 'undefined' && S.frame === 'custom' && document.readyState === 'complete'"):
                break
        except Exception as e:                                 # (the debugging port is not up yet)
            page = None
            last = e
        time.sleep(0.5)
    else:
        say("the page was not reached through the debugging port: %s" % (last if page is None else "no custom frame"))
        page = None
    say("page ready after %.1f s" % (time.time() - started))
    if page:
        page.run("window.__bar = []; ['mousedown', 'mouseup'].forEach(function (t) { window.addEventListener(t, function (e) { "
                 "window.__bar.push([Math.round(performance.now()), t, e.isTrusted, e.clientX, e.clientY, "
                 "(e.target.id || e.target.className || e.target.tagName)]); }, true); }); 1")
    time.sleep(1.0)
    wa = work_area()
    say("screen %sx%s, work area %s, dpi %s" % (SCREEN[0], SCREEN[1], wa, user32.GetDpiForSystem()))
    say("window rect %s, client origin %s, style 0x%08x" % (rect_of(hwnd), client_origin(hwnd), user32.GetWindowLongW(hwnd, -16) & 0xFFFFFFFF))
    check(http(port, "/api/state").get("frame") == "custom", "the page's own bar is the title bar")
    user32.SetForegroundWindow(hwnd)
    normal(hwnd)
    tests(port, hwnd, page, wa)
    say("---- logs after the run ----")
    for name in ("sourcerer.log", "console.log"):
        try:
            lines = (data / "Logs" / name).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        say("[%s]" % name)
        for line in lines[-30:]:
            say("  " + line)


def tests(port, hwnd, page, wa):
    half = (wa[2] - wa[0]) // 2

    # 1. the bar moves the window
    for attempt in (1, 2):
        normal(hwnd)
        before = rect_of(hwnd)
        start = bar_point(hwnd)
        drag(start, (start[0] + 150, start[1] + 60))
        after = rect_of(hwnd)
        dx, dy = after[0] - before[0], after[1] - before[1]
        say("drag %d: moved by (%d, %d); page events %s" % (attempt, dx, dy, events(page)))
        check(abs(dx - 150) <= 14 and abs(dy - 60) <= 14, "the bar moves the window with the pointer (%d)" % attempt)

    # 2. dock left, then pull out
    normal(hwnd)
    drag(bar_point(hwnd), (0, wa[1] + 300))
    r = rect_of(hwnd)
    say("dock left: %s %s" % (r, flags(page, hwnd)))
    check(abs(r[0] - wa[0]) <= 2 and abs(r[1] - wa[1]) <= 2 and abs(r[3] - wa[3]) <= 8 and r[2] - r[0] <= 780 and not zoomed(hwnd),
          "a drag to the left edge docks the window there (full height, narrower than 780)")
    start = bar_point(hwnd, dx=200)
    drag(start, (start[0] + 120, start[1] + 150))
    r = rect_of(hwnd)
    say("pulled out of the left dock: %s %s" % (r, flags(page, hwnd)))
    check(abs((r[2] - r[0]) - 800) <= 8 and abs((r[3] - r[1]) - 560) <= 8, "a drag out of the dock gives the window its size back (800x560)")

    # 3. dock right
    normal(hwnd)
    drag(bar_point(hwnd), (SCREEN[0] - 1, wa[1] + 300))
    r = rect_of(hwnd)
    say("dock right: %s %s" % (r, flags(page, hwnd)))
    check(abs(r[2] - wa[2]) <= 2 and abs(r[1] - wa[1]) <= 2 and abs(r[3] - wa[3]) <= 8 and r[2] - r[0] <= 780 and not zoomed(hwnd),
          "a drag to the right edge docks the window there")

    # 4. dock top = maximize, then pull out
    normal(hwnd)
    drag(bar_point(hwnd), (SCREEN[0] // 2, 0))
    r = rect_of(hwnd)
    say("dock top: %s zoomed=%s %s" % (r, zoomed(hwnd), flags(page, hwnd)))
    check(zoomed(hwnd) and abs(r[0] - wa[0]) <= 2 and abs(r[2] - wa[2]) <= 2 and abs(r[3] - wa[3]) <= 2,
          "a drag to the top edge maximizes the window into the work area")
    start = bar_point(hwnd, dx=400)
    drag(start, (start[0] + 60, start[1] + 200))
    r = rect_of(hwnd)
    say("pulled out of the maximized window: %s zoomed=%s %s" % (r, zoomed(hwnd), flags(page, hwnd)))
    check(not zoomed(hwnd) and abs((r[2] - r[0]) - 800) <= 8, "a drag out of a maximized window gives it its size back")

    # 5. a corner is a quarter
    normal(hwnd)
    drag(bar_point(hwnd), (0, 0))
    r = rect_of(hwnd)
    say("dock top left: %s %s" % (r, flags(page, hwnd)))
    check(abs(r[0] - wa[0]) <= 2 and abs(r[1] - wa[1]) <= 2 and r[2] - r[0] <= 780 and r[3] - r[1] <= 560 and not zoomed(hwnd),
          "a drag to a corner docks the window as a quarter")

    # 6. a double-click on the bar maximizes, and again restores
    normal(hwnd)
    p = bar_point(hwnd)
    for expected in (True, False):
        p = bar_point(hwnd)
        point(*p)
        time.sleep(0.3)
        down(); up(); time.sleep(0.08); down(); up()
        time.sleep(1.0)
        check(zoomed(hwnd) == expected, "a double-click on the bar %s the window" % ("maximizes" if expected else "restores"))

    # 7. a dialog open: the bar still moves the window
    normal(hwnd)
    if page:
        page.run("document.getElementById('btn-settings').click(); 1")
        time.sleep(1.5)
        before = rect_of(hwnd)
        start = bar_point(hwnd)
        drag(start, (start[0] + 120, start[1] + 50))
        after = rect_of(hwnd)
        say("drag under a dialog: moved by (%d, %d) %s" % (after[0] - before[0], after[1] - before[1], events(page)))
        check(abs(after[0] - before[0] - 120) <= 14 and abs(after[1] - before[1] - 50) <= 14, "the bar moves the window under a modal dialog")
        page.run("document.getElementById('dlg-settings').close(); 1")


if __name__ == "__main__":
    sys.exit(main())
