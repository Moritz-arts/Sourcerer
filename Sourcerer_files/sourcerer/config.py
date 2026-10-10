"""Paths and the version. Everything imports this; it imports nothing of ours."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent          # Sourcerer_files/
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
STATIC = ROOT / "static"

# Machine state: never shipped, never replaced by an update.
USERDATA = ROOT / "Userdata"
DB_PATH = USERDATA / "sourcerer.db"
LOG_DIR = USERDATA / "Logs"
# Where new files go until a folder is chosen in Settings -- inside the
# installation, so nothing is written elsewhere without being asked.
DEFAULT_LIBRARY = USERDATA / "Library"

USER_AGENT = "Sourcerer/%s (+https://github.com/Moritz-arts/Sourcerer)" % VERSION
