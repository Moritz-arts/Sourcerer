"""Paths, the version and the settings' defaults. Everything imports this; it imports nothing of ours."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent          # Sourcerer_files/
INSTALL = ROOT.parent                                           # the folder with the launchers
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
STATIC = ROOT / "static"
REPO = "Moritz-arts/Sourcerer"

# Machine state: never shipped, never replaced by an update.
USERDATA = ROOT / "Userdata"
DB_PATH = USERDATA / "sourcerer.db"
LOG_DIR = USERDATA / "Logs"
THUMBS = USERDATA / "Thumbs"
AVATARS = USERDATA / "Avatars"
# An update is unpacked here: inside Userdata, which the update carries
# across, so the install folder never shows a stray staging folder.
UPDATE_DIR = USERDATA / "_update"
# Where new files go until a folder is chosen in Settings -- inside the
# installation, so nothing is written elsewhere without being asked.
DEFAULT_LIBRARY = USERDATA / "Library"

USER_AGENT = "Sourcerer/%s (+https://github.com/%s)" % (VERSION, REPO)

# Every setting and what it is until somebody changes it. Stored as text.
DEFAULTS = {
    "library": "",              # empty: DEFAULT_LIBRARY
    "filenames": "original",    # 'original' or 'dated' (<date>_<original>)
    "card_size": "230",         # px, the smallest width a card may have
    "theme": "system",          # 'system', 'light', 'dark'
    "auto_sync": "0",           # '1': sync every card on its own
    "auto_hours": "6",          # how often, in hours
    "last_auto": "",            # when it last did
    "parallel": "4",            # downloads at once, all sites together
    "per_host": "2",            # downloads at once from one site
    "pace_ms": "250",           # pause between two requests to one site
    "channel": "stable",        # updates: 'stable' (releases) or 'beta' (newest build)
}
