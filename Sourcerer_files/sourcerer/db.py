"""SQLite: artists, their sources, every file ever seen, and settings.

One connection per call site and thread -- the server's request threads and the
sync thread each open their own, and WAL lets them read while one writes.
"""
import shutil
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS artists (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    notes    TEXT NOT NULL DEFAULT '',
    created  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY,
    artist_id     INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    kind          TEXT NOT NULL,
    -- 1 once a sync has walked the whole history; until then every sync
    -- pages to the end, so an interrupted first sync is finished later.
    complete      INTEGER NOT NULL DEFAULT 0,
    last_checked  TEXT,
    last_error    TEXT
);
-- Every file ever seen, kept or not: path is NULL for a byte-identical
-- duplicate. remote_key is per artist, not per source, so removing a source
-- and adding it again does not download everything a second time -- and a
-- file somebody deleted from the library is not brought back.
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY,
    artist_id   INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    source_id   INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    remote_key  TEXT NOT NULL,
    sha256      TEXT,
    path        TEXT,
    post_url    TEXT,
    posted      TEXT,
    created     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (artist_id, remote_key)
);
CREATE INDEX IF NOT EXISTS files_sha ON files (artist_id, sha256);
-- The files of deleted cards. A card made again for the same artist finds
-- them here (by remote_key) and takes over those still on disk instead of
-- downloading them a second time.
CREATE TABLE IF NOT EXISTS archive (
    remote_key  TEXT PRIMARY KEY,
    sha256      TEXT,
    path        TEXT,
    post_url    TEXT,
    posted      TEXT,
    phash       TEXT,
    width       INTEGER,
    height      INTEGER,
    size        INTEGER
);
-- Files that failed to download, per sync. After sync.GIVE_UP failures a file
-- no longer keeps its source from completing (which would walk its whole
-- history again on every sync).
CREATE TABLE IF NOT EXISTS failures (
    artist_id   INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    remote_key  TEXT NOT NULL,
    count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (artist_id, remote_key)
);
-- The newest posts of a source as the last look at it left them (snapshots.py): Browse opens
-- from this at once and checks the site meanwhile; cards count what is new from it.
CREATE TABLE IF NOT EXISTS snapshots (
    source_id   INTEGER PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    fetched     TEXT NOT NULL,
    -- when the oldest posts in it were last seen on the site (older than fetched once a merge carried
    -- posts over): their links expire
    tail        TEXT,
    data        BLOB NOT NULL
);
-- The followed accounts a login's list has shown (follows.py), by profile URL: each becomes a card once,
-- so a card the user deleted or merged away does not come back with the next look at the list.
-- url is lower-cased (handles and user names do not care). avatar/headers: the profile picture the list named,
-- fetched later by a worker that survives a restart; tried: failed fetches.
CREATE TABLE IF NOT EXISTS followed (
    url      TEXT PRIMARY KEY,
    added    TEXT NOT NULL DEFAULT (datetime('now')),
    avatar   TEXT NOT NULL DEFAULT '',
    headers  TEXT NOT NULL DEFAULT '',
    tried    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""

# Columns added after the first version. A database made before them gets them
# at start, so nothing a user already has needs to be thrown away.
COLUMNS = {
    "artists": {
        # 'together': <artist>/ -- 'per_source': <artist>/<site>/
        "layout": "TEXT NOT NULL DEFAULT 'together'",
        # 'keep_all', 'best' (highest resolution wins) or 'master' (that source wins)
        "dedupe": "TEXT NOT NULL DEFAULT 'best'",
        "master_source_id": "INTEGER",
        "last_sync": "TEXT",
        "last_activity": "TEXT",          # last time something new arrived
        "last_new": "INTEGER NOT NULL DEFAULT 0",
        "last_failed": "INTEGER NOT NULL DEFAULT 0",
        "folder": "TEXT",                 # chosen on the card; NULL: <library>/<name>
        "avatar": "TEXT",                 # (v0.32 and older: a file name in Userdata/Avatars -- nothing is kept now)
        "avatar_url": "TEXT",             # where the site has the profile picture: the page shows it through /api/avatar
        "avatar_headers": "TEXT",         # JSON: what that address wants with the request (pixiv: a Referer)
        "avatar_checked": "TEXT",         # when the profile picture's address was last looked for
        "previews_at": "TEXT",            # (v0.32 and older: previews; unused)
        # 1: a sync that finds new posts downloads them too (sync alone only refreshes: it looks at the
        # sources and counts what is new). Cards made before this setting keep downloading: see init().
        "auto_download": "INTEGER NOT NULL DEFAULT 0",
        "pending": "INTEGER NOT NULL DEFAULT 0",   # new posts the last look found that are not downloaded
        # 1: made from a login's follows and not touched since -- it is only in the list. No look in the
        # background (previews, Sync all, automatic sync) and not in "All artists" until the user does
        # something with the card (edits it, syncs it, turns auto-download on, merges it).
        "listed": "INTEGER NOT NULL DEFAULT 0",
        "favorite": "INTEGER NOT NULL DEFAULT 0",   # 1: starred by the user (the list can put these first)
    },
    "snapshots": {"tail": "TEXT"},
    "sources": {
        # 'ok', 'warn' (works with a catch: login, bot check, slow down) or 'error'
        "last_level": "TEXT",
        "walked": "TEXT",                 # when a sync last went through all of it
        "links": "TEXT",                  # JSON: the accounts its own profile names (sources.profile_links): who is the same artist
        "pending": "INTEGER NOT NULL DEFAULT 0",   # its newest posts a look found that are not in the library
        "pending_keys": "TEXT",            # JSON: the remote_keys of those (at most sync.PENDING_KEYS), so a download from Browse can tell
        "latest": "TEXT",                  # when its newest post was made (UTC, "YYYY-MM-DD HH:MM:SS"), from the last look at it
    },
    "files": {
        "phash": "TEXT",                  # imaging fingerprint; NULL for video
        "width": "INTEGER",
        "height": "INTEGER",
        "size": "INTEGER",
    },
}


def connect():
    con = sqlite3.connect(config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init():
    config.USERDATA.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(SCHEMA)
        for table, columns in COLUMNS.items():
            have = {row[1] for row in con.execute("PRAGMA table_info(%s)" % table)}
            for name, decl in columns.items():
                if name not in have:
                    con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, decl))
        # Sync used to download; cards that exist now keep doing it (auto-download on), once.
        if not con.execute("SELECT 1 FROM settings WHERE key = 'auto_download_migrated'").fetchone():
            con.execute("UPDATE artists SET auto_download = 1")
            con.execute("INSERT INTO settings (key, value) VALUES ('auto_download_migrated', '1')")
        _forget_what_was_kept(con)
        # What profiles name (sources.links) comes with the lists of followed accounts: read to their end once more.
        if not con.execute("SELECT 1 FROM settings WHERE key = 'follow_links_v1'").fetchone():
            con.execute("DELETE FROM settings WHERE key LIKE 'follows_read:%'")
            con.execute("INSERT INTO settings (key, value) VALUES ('follow_links_v1', '1')")
        # The speed settings were set to values worked out for the sites' limits (v0.33): whatever was chosen
        # before -- most of it just the old defaults saved by a change of another row -- is dropped, once.
        if not con.execute("SELECT 1 FROM settings WHERE key = 'speed_defaults_v2'").fetchone():
            con.execute("DELETE FROM settings WHERE key IN ('parallel', 'per_host', 'pace_ms', 'login_gap')")
            con.execute("INSERT INTO settings (key, value) VALUES ('speed_defaults_v2', '1')")


def _forget_what_was_kept(con):
    """Sourcerer keeps no pictures of its own: v0.32 and older kept a profile picture per artist (Userdata/Avatars) and
    small copies of each card's newest posts (Userdata/Previews, table previews). The cards are gone and the page
    shows a profile picture from the site's own address, through memory. Once: the address the follows list named
    is taken from `followed`, the cards without one look for it again at the next sync, and the folders go."""
    con.execute("DROP TABLE IF EXISTS previews")
    shutil.rmtree(config.PREVIEWS, ignore_errors=True)
    if con.execute("SELECT 1 FROM settings WHERE key = 'avatars_in_memory'").fetchone():
        return
    con.execute("UPDATE artists SET avatar_url = (SELECT f.avatar FROM followed f JOIN sources s ON lower(s.url) = f.url "
                "WHERE s.artist_id = artists.id AND f.avatar != '' ORDER BY f.rowid DESC LIMIT 1), "
                "avatar_headers = (SELECT NULLIF(f.headers, '') FROM followed f JOIN sources s ON lower(s.url) = f.url "
                "WHERE s.artist_id = artists.id AND f.avatar != '' ORDER BY f.rowid DESC LIMIT 1), "
                "avatar_checked = NULL WHERE avatar_url IS NULL")
    con.execute("UPDATE artists SET avatar_checked = datetime('now') WHERE avatar_url IS NOT NULL")
    con.execute("UPDATE artists SET avatar = NULL")
    shutil.rmtree(config.AVATARS, ignore_errors=True)
    con.execute("INSERT INTO settings (key, value) VALUES ('avatars_in_memory', '1')")


def get_setting(key, default=None):
    with connect() as con:
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row:
        return row["value"]
    return config.DEFAULTS.get(key) if default is None else default


def settings():
    with connect() as con:
        stored = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM settings")}
    return dict(config.DEFAULTS, **{k: v for k, v in stored.items() if k in config.DEFAULTS})


def setting_int(key, low, high):
    """An integer setting, kept inside the range the program can work with."""
    try:
        value = int(get_setting(key))
    except (TypeError, ValueError):
        value = int(config.DEFAULTS[key])
    return max(low, min(high, value))


def set_setting(key, value):
    with connect() as con:
        con.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))
