"""Drives Sourcerer's real window on a Windows runner with the real mouse and says what the window did.

Run by .github/workflows/window-test.yml (Windows only): starts Sourcerer from source, finds its window, presses the page's
own bar with injected mouse events and moves the pointer, then reads where the window is. Everything is printed -- a failing
line starts with FAIL -- and the logs of the run are kept in ./window-test for the workflow to upload.
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
LOGS = ROOT / "Sourcerer_files" / "Userdata" / "Logs"
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDPIAware()
FAILS = []


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND), ("hwndMoveSize", wintypes.HWND),
                ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]


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


# ---- the window and the mouse
SCREEN = (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


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


def cursor():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def in_move_size(hwnd):
    thread = user32.GetWindowThreadProcessId(hwnd, None)
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    return bool(user32.GetGUIThreadInfo(thread, ctypes.byref(info)) and info.flags & 0x2)


def drag(hwnd, start, end, steps=24, pause=0.02, hold=0.25, watch=None):
    """Press at `start`, move to `end` in steps, release. `watch(step)` runs while the button is down."""
    point(*start)
    time.sleep(0.3)
    down()
    time.sleep(hold)
    if watch:
        watch(0)
    for i in range(1, steps + 1):
        point(start[0] + (end[0] - start[0]) * i / steps, start[1] + (end[1] - start[1]) * i / steps)
        time.sleep(pause)
        if watch:
            watch(i)
    time.sleep(0.25)
    up()
    time.sleep(0.9)


def bar_point(hwnd, dx=31, dy=26):
    """The brand mark in the page's bar (CSS px from the client origin; the runner is 100 %)."""
    cx, cy = client_origin(hwnd)
    return cx + dx, cy + dy


def show_logs(title):
    say("---- %s ----" % title)
    for name in ("sourcerer.log", "console.log"):
        try:
            lines = (LOGS / name).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        say("[%s]" % name)
        for line in lines[-25:]:
            say("  " + line)


def main():
    OUT.mkdir(exist_ok=True)
    env = dict(os.environ, SOURCERER_DETACHED="1", PYTHONUNBUFFERED="1")
    app = subprocess.Popen([sys.executable, str(ROOT / "Sourcerer_files" / "app.py")], cwd=str(ROOT), env=env,
                           stdout=open(OUT / "app.out", "w"), stderr=subprocess.STDOUT)
    try:
        run(app)
    finally:
        app.kill()
        for name in ("sourcerer.log", "console.log"):
            try:
                (OUT / name).write_text((LOGS / name).read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            except OSError:
                pass
    say("")
    say("%d check(s) failed: %s" % (len(FAILS), "; ".join(FAILS)) if FAILS else "all window checks passed")
    return 1 if FAILS and os.environ.get("WINDOW_TEST_STRICT") else 0


def run(app):
    running = ROOT / "Sourcerer_files" / "Userdata" / "running.json"
    port = None
    for _ in range(120):
        try:
            port = json.loads(running.read_text(encoding="utf-8"))["port"]
            http(port, "/api/ping")
            break
        except (OSError, ValueError, KeyError):
            port = None
            time.sleep(0.5)
    check(port is not None, "Sourcerer serves")
    if port is None:
        return
    hwnd = None
    for _ in range(120):
        hwnd = find_window()
        if hwnd:
            break
        time.sleep(0.5)
    check(hwnd is not None, "the app window opens")
    if not hwnd:
        return
    state = {}
    for _ in range(60):
        state = http(port, "/api/state")
        if state.get("frame") == "custom":
            break
        time.sleep(0.5)
    time.sleep(3)                                              # the page draws its bar
    say("screen %sx%s, work area %s, dpi %s" % (SCREEN[0], SCREEN[1], work_area(), user32.GetDpiForSystem()))
    say("window rect %s, client origin %s, style 0x%08x" % (rect_of(hwnd), client_origin(hwnd), user32.GetWindowLongW(hwnd, -16) & 0xFFFFFFFF))
    say("state: frame=%s drag=%s" % (state.get("frame"), state.get("drag")))
    check(state.get("frame") == "custom", "the page's own bar is the title bar")
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    moves_and_docks(port, hwnd)
    show_logs("logs after the run")


def moved(hwnd, before):
    now = rect_of(hwnd)
    return now[0] - before[0], now[1] - before[1]


def moves_and_docks(port, hwnd):
    # 1. a plain drag of the bar, three times (the second and third show a fallback if there is one)
    for attempt in (1, 2, 3):
        before = rect_of(hwnd)
        seen = []
        drag(hwnd, bar_point(hwnd), (bar_point(hwnd)[0] + 150, bar_point(hwnd)[1] + 60),
             watch=lambda step: seen.append(in_move_size(hwnd)) if step in (0, 12, 24) else None)
        dx, dy = moved(hwnd, before)
        say("drag %d: window moved by (%d, %d); in a move loop while held: %s; drag mode now: %s" % (
            attempt, dx, dy, seen, http(port, "/api/state").get("drag")))
        check(abs(dx - 150) <= 12 and abs(dy - 60) <= 12, "drag %d moves the window with the pointer" % attempt)
        # back to where it was
        r = rect_of(hwnd)
        user32.SetWindowPos(hwnd, None, before[0], before[1], 0, 0, 0x0001 | 0x0004 | 0x0010)
        time.sleep(0.3)

    # 2. docking: to the left edge, the right edge, the top edge
    wa = work_area()
    for name, target in (("left", (0, wa[1] + 300)), ("right", (SCREEN[0] - 1, wa[1] + 300)), ("top", (SCREEN[0] // 2, 0))):
        before = rect_of(hwnd)
        drag(hwnd, bar_point(hwnd), target, steps=30)
        after = rect_of(hwnd)
        say("dock %s: %s -> %s (work area %s)" % (name, before, after, wa))
        if name == "left":
            check(abs(after[0] - wa[0]) <= 2 and abs((after[2] - after[0]) - (wa[2] - wa[0]) // 2) <= 16, "dragged to the left edge: left half")
        elif name == "right":
            check(abs(after[2] - wa[2]) <= 2 and abs((after[2] - after[0]) - (wa[2] - wa[0]) // 2) <= 16, "dragged to the right edge: right half")
        else:
            check(abs(after[0] - wa[0]) <= 2 and abs(after[2] - wa[2]) <= 2 and abs(after[3] - wa[3]) <= 2, "dragged to the top edge: maximized")
        # pulled out again: the window comes back to a normal size under the pointer
        mid = bar_point(hwnd)
        before = rect_of(hwnd)
        drag(hwnd, (mid[0] + 100, mid[1]), (mid[0] + 100 + 80, mid[1] + 240), steps=20)
        out = rect_of(hwnd)
        say("pulled out of %s: %s -> %s" % (name, before, out))
        check((out[2] - out[0]) != (before[2] - before[0]), "pulled out of %s: the window gets its normal size back" % name)
        user32.SetWindowPos(hwnd, None, 120, 40, 0, 0, 0x0001 | 0x0004 | 0x0010)
        time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
