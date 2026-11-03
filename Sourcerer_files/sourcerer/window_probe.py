"""The child process of desktop._window_problem: can Qt open a window here?

It imports Qt and nothing of Sourcerer: the check runs at every start on Linux, and `from sourcerer import desktop` used to load
the whole program (flask, requests, Pillow, the database) into the child first -- up to 0.7 s for nothing."""


def main():
    """Exit code 0 only if Qt can open a window here. Qt aborts the process when it cannot (no display, a library of the xcb
    platform plugin missing), which no `except` sees -- that is why this runs in a child."""
    from qtpy.QtWidgets import QApplication
    from qtpy.QtWebEngineWidgets import QWebEngineView  # noqa: F401 -- Qt wants it before the application
    QApplication([])
    return 0
