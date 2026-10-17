"""Paths, the version and the settings' defaults. Everything imports this; it imports nothing of ours."""
import os
import pathlib
import sys

# True in the standalone builds (PyInstaller: Sourcerer.exe, the macOS app, the Linux binary): Python
# is inside, there is no venv, no launch.py and no pip. On Windows and in the Linux tar.gz the bundle's
# folder is named Sourcerer_files too, so ROOT, USERDATA and STATIC mean the same there as in the repository.
FROZEN = bool(getattr(sys, "frozen", False))
ROOT = pathlib.Path(getattr(sys, "_MEIPASS", "") or pathlib.Path(__file__).resolve().parent.parent)  # Sourcerer_files/
INSTALL = ROOT.parent                                           # the folder with the launchers (or Sourcerer.exe)
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
STATIC = ROOT / "static"
REPO = "Moritz-arts/Sourcerer"

# Machine state: never shipped, never replaced by an update.
# Beside the program wherever that is writable and ours (the repository, Windows, the Linux tar.gz).
# Not inside a macOS .app (signed, and read-only when opened from the disk image) nor an AppImage
# (a read-only mount): there it lives in the user's own data folder.
APPIMAGE = os.environ.get("APPIMAGE") if sys.platform.startswith("linux") else None
_HOME_DATA = None
if FROZEN and sys.platform == "darwin":
    _HOME_DATA = pathlib.Path.home() / "Library" / "Application Support" / "Sourcerer"
elif FROZEN and APPIMAGE:
    _HOME_DATA = pathlib.Path(os.environ.get("XDG_DATA_HOME") or pathlib.Path.home() / ".local" / "share") / "Sourcerer"
USERDATA = (_HOME_DATA / "Userdata") if _HOME_DATA else ROOT / "Userdata"
DB_PATH = USERDATA / "sourcerer.db"
LOG_DIR = USERDATA / "Logs"
AVATARS = USERDATA / "Avatars"
PREVIEWS = USERDATA / "Previews"     # the pictures cards show before anything is downloaded (a cache)
# An update is unpacked here: inside Userdata, which the update carries
# across, so the install folder never shows a stray staging folder.
UPDATE_DIR = USERDATA / "_update"
# Where new files go until a folder is chosen in Settings -- inside the
# installation, so nothing is written elsewhere without being asked. Where Userdata is out
# of sight (macOS' Library, a hidden .local) the pictures go to a folder the user can find.
DEFAULT_LIBRARY = (pathlib.Path.home() / "Pictures" / "Sourcerer") if _HOME_DATA else USERDATA / "Library"

# The crawler convention (as Googlebot's): "Mozilla/5.0 (compatible; ...)" names
# Sourcerer and where it comes from, and passes the CDNs that challenge any
# User-Agent not starting with Mozilla/5.0 -- pixiv's Cloudflare did, for logged-in requests.
USER_AGENT = "Mozilla/5.0 (compatible; Sourcerer/%s; +https://github.com/%s)" % (VERSION, REPO)

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
    "gdl_updated": "",          # when gallery-dl was last brought up to date (weekly)
    "update_seen": "",          # the update helper's last run that was already reported
}
