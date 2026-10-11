"""Sourcerer's entry point. launch.py starts this file in the prepared environment."""
import pathlib
import sys

# pythonw.exe has no console, and print() or a traceback would go nowhere.
# launch.py hands its log file over as stdout; started any other way, this is it.
if sys.stdout is None or sys.stderr is None:
    _log = pathlib.Path(__file__).resolve().parent / "Userdata" / "Logs" / "console.log"
    _log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)

from sourcerer.desktop import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
