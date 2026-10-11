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
import json
import logging
import logging.handlers
import os
import shutil
import threading
import time
import webbrowser

from werkzeug.serving import make_server

from . import config, db, net, server, sync

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
    """The update helper's last lines, as one line in the activity log."""
    if not os.environ.pop("SOURCERER_AFTER_UPDATE", ""):
        return
    try:
        last = (config.LOG_DIR / "update.log").read_text(encoding="utf-8").splitlines()[-1]
    except (OSError, IndexError):
        last = ""
    if last.endswith("  done"):
        sync.event("done", "Updated to v%s" % config.VERSION)
    elif last.endswith("  restarting"):
        sync.event("info", "Restarted")
    elif last.endswith("  old version restored"):
        sync.event("error", "The update failed; the previous version was put back. "
                   "Details: Settings > Updates")
    else:
        sync.event("error", "The update did not go through: %s -- see Settings > Updates"
                   % last.split("  ", 1)[-1])


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
    args = parser.parse_args(argv)

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
    httpd = make_server("127.0.0.1", args.port, server.app, threaded=True)
    url = "http://127.0.0.1:%d/" % httpd.server_port
    threading.Thread(target=httpd.serve_forever, daemon=True, name="server").start()
    log.info("Sourcerer v%s at %s", config.VERSION, url)
    server.URL = url
    _announce(httpd.server_port)
    try:
        if not (args.browser or args.no_open):
            try:
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
