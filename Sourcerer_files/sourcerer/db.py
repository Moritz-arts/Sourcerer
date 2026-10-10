"""SQLite: artists, their sources, every file ever seen, and settings.

One connection per call site and thread -- the server's request threads and the
sync thread each open their own, and WAL lets them read while one writes.
"""
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


def get_setting(key, default=None):
    with connect() as con:
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with connect() as con:
        con.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))
