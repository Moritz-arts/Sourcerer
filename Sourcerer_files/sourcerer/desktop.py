"""main(): logging, database, the server in a thread, then the window -- or the browser.

The window is pywebview, as in TrackImage. Where it cannot open (the package
did not install, no WebView2 on Windows, no GTK/Qt bindings on Linux), the
same page opens in the default browser and this console keeps Sourcerer
running until it is closed.
"""
import argparse
import logging
import logging.handlers
import threading
import time
import webbrowser

from werkzeug.serving import make_server

from . import config, db, server

log = logging.getLogger("sourcerer")


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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sourcerer")
    parser.add_argument("--browser", action="store_true", help="open in the browser, not a window")
    parser.add_argument("--no-open", action="store_true", help="open nothing; just serve")
    parser.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: any free)")
    args = parser.parse_args(argv)

    _logging()
    db.init()
    httpd = make_server("127.0.0.1", args.port, server.app, threaded=True)
    url = "http://127.0.0.1:%d/" % httpd.server_port
    threading.Thread(target=httpd.serve_forever, daemon=True, name="server").start()
    log.info("Sourcerer v%s at %s", config.VERSION, url)

    if not (args.browser or args.no_open):
        try:
            import webview
            server.WINDOW = webview.create_window(
                "Sourcerer v%s" % config.VERSION, url, width=1280, height=860, min_size=(760, 520))
            webview.start()
            return 0                                          # the window was closed
        except Exception as e:
            server.WINDOW = None
            log.info("No app window (%s) -- opening the browser instead.", e)

    if not args.no_open:
        webbrowser.open(url)
    print("\n  Sourcerer runs at %s -- close this window to stop it.\n" % url, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0
