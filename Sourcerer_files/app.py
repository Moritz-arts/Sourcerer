"""Sourcerer's entry point. launch.py starts this file in the prepared environment."""
import os
import sys

# Standalone build: the exe is its own Python, so gallery-dl (a separate process, see
# sources/_gdl.py) is Sourcerer.exe started with --gallery-dl. Before anything else is imported.
if getattr(sys, "frozen", False) and sys.argv[1:2] == ["--gallery-dl"]:
    sys.argv = ["gallery-dl"] + sys.argv[2:]
    import gallery_dl
    sys.exit(gallery_dl.main())

# pythonw.exe has no console, and print() or a traceback would go nowhere.
# launch.py hands its log file over as stdout; started any other way, this is it.
if sys.stdout is None or sys.stderr is None:
    from sourcerer import config      # imports only the standard library; knows where Userdata is
    _log = config.LOG_DIR / "console.log"
    _log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)

if getattr(sys, "frozen", False):
    os.environ.setdefault("SOURCERER_DETACHED", "1")     # a windowed exe has no console to close either

from sourcerer.desktop import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
