"""Paths, the version and the settings' defaults. Everything imports this; it imports nothing of ours."""
import os
import pathlib
import sys

# True in the standalone builds (PyInstaller: Sourcerer.exe, the macOS app, the Linux binary): Python
# is inside, there is no venv, no launch.py and no pip. Windows and the Linux tar.gz are ONE executable
# that unpacks itself to a temp folder (ROOT is that folder: static files and VERSION, read only);
# the AppImage and the macOS app hold the unpacked program (ROOT is inside them).
FROZEN = bool(getattr(sys, "frozen", False))
ROOT = pathlib.Path(getattr(sys, "_MEIPASS", "") or pathlib.Path(__file__).resolve().parent.parent)  # Sourcerer_files/
# The folder with the launchers -- or the one Sourcerer.exe is in.
INSTALL = pathlib.Path(sys.executable).resolve().parent if FROZEN else ROOT.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
STATIC = ROOT / "static"
REPO = "Moritz-arts/Sourcerer"

# Machine state: never shipped, never replaced by an update.
# Beside the program wherever that is ours and writable: the repository (Sourcerer_files/Userdata) and
# the one-file builds (Userdata/ next to the executable). Not inside a macOS .app (signed, and read-only
# when opened from the disk image) nor an AppImage (a read-only mount): there it lives in the user's own
# data folder.
APPIMAGE = os.environ.get("APPIMAGE") if sys.platform.startswith("linux") else None
_HOME_DATA = None
if FROZEN and sys.platform == "darwin":
    _HOME_DATA = pathlib.Path.home() / "Library" / "Application Support" / "Sourcerer"
elif FROZEN and APPIMAGE:
    _HOME_DATA = pathlib.Path(os.environ.get("XDG_DATA_HOME") or pathlib.Path.home() / ".local" / "share") / "Sourcerer"
if _HOME_DATA:
    USERDATA = _HOME_DATA / "Userdata"
elif FROZEN:
    USERDATA = INSTALL / "Userdata"
    # Up to v0.21 the Windows and Linux builds were a folder with Userdata inside Sourcerer_files/.
    # Somebody who unpacks the new one-file build over it keeps their data where it is.
    _OLD = INSTALL / "Sourcerer_files" / "Userdata"
    if _OLD.is_dir() and not USERDATA.exists():
        USERDATA = _OLD
else:
    USERDATA = ROOT / "Userdata"
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
    "grid_quality": "best",     # 'fast': the sites' small pictures in the grid; 'best': the largest rendition below the original
    "tile_logo": "1",           # '0': no site mark on the pictures of the gallery
    "login_gap": "normal",     # the pause between two artists on a site where a login can get banned: 'careful', 'normal', 'fast'
    "scan_on_start": "1",       # '1': every start looks for new posts of every card, as Refresh does
    "auto_sync": "0",           # '1': sync every card on its own
    "auto_hours": "6",          # how often, in hours
    "import_follows": "1",      # '1': the accounts a login follows become artists in the list (follows.py)
    "last_auto": "",            # when it last did
    "parallel": "4",            # downloads at once, all sites together
    "per_host": "2",            # downloads at once from one site
    "pace_ms": "250",           # pause between two requests to one site
    "channel": "stable",        # updates: 'stable' (the latest release) or 'beta' (the main branch)
    "gdl_updated": "",          # when gallery-dl was last brought up to date (weekly)
    "update_seen": "",          # the update helper's last run that was already reported
}
