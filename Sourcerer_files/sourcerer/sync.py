"""Runs the sources of artists, downloads what is new, keeps one copy of each file.

One sync at a time, in a background thread; the window polls status(). A file
is new when its remote key has never been seen for this artist. It is kept
unless the same bytes already sit in the artist's folder under another name
(the same picture posted on two sites) -- then only the key is recorded, so
it is not fetched again. Pictures that merely look alike are TrackImage's job.
"""
import collections
import datetime
import logging
import os
import pathlib
import re
import threading

from . import config, db, net, sources

log = logging.getLogger(__name__)

# The first sync of a source walks its whole history, page by page. A ceiling,
# so an account with years of posts cannot keep a sync running for a day.
MAX_PAGES = int(os.environ.get("SOURCERER_MAX_PAGES", "500"))

_lock = threading.Lock()
_state = {"running": False, "artist": "", "source": "", "new": 0, "duplicates": 0,
          "errors": 0, "message": "Idle", "finished": None}
_log = collections.deque(maxlen=300)


def status():
    with _lock:
        return dict(_state, log=list(_log))


def _note(message, level=logging.INFO, **fields):
    log.log(level, message)
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    with _lock:
        _state.update(fields, message=message)
        _log.append("%s  %s" % (stamp, message))


def library():
    return db.get_setting("library") or str(config.DEFAULT_LIBRARY)


def safe_name(name):
    """A folder name every system accepts: no reserved characters, no trailing dot."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(".")
    if name.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?i)(COM|LPT)\d", name):
        name = "_" + name
    return name[:120] or "Unnamed"


def artist_folder(name):
    return pathlib.Path(library()) / safe_name(name)


def start(artist_ids=None):
    """Start a sync of the given artists (all when None); False if one is running."""
    with _lock:
        if _state["running"]:
            return False
        _state.update(running=True, new=0, duplicates=0, errors=0, artist="", source="",
                      message="Starting...")
    threading.Thread(target=_run, args=(artist_ids,), daemon=True, name="sync").start()
    return True


def _run(artist_ids):
    try:
        with db.connect() as con:
            rows = con.execute("SELECT id, name FROM artists ORDER BY name COLLATE NOCASE").fetchall()
        for artist in rows:
            if artist_ids is None or artist["id"] in artist_ids:
                sync_artist(artist["id"], artist["name"])
        with _lock:
            done = "Done: %d new, %d duplicates skipped, %d errors." % (
                _state["new"], _state["duplicates"], _state["errors"])
        _note(done)
    except Exception as e:                                   # never leave "running" stuck
        log.exception("sync failed")
        _note("Sync failed: %s" % e, logging.ERROR)
    finally:
        with _lock:
            _state.update(running=False, artist="", source="",
                          finished=datetime.datetime.now().isoformat(timespec="seconds"))


def sync_artist(artist_id, name):
    with db.connect() as con:
        rows = con.execute("SELECT * FROM sources WHERE artist_id = ? ORDER BY id",
                           (artist_id,)).fetchall()
    for src in rows:
        site = sources.site_for(src["url"])
        if not site:
            continue
        _note("%s: checking %s" % (name, src["url"]), artist=name, source=src["url"])
        error = None
        try:
            complete = _sync_source(artist_id, name, src, site)
        except Exception as e:
            error = str(e) or e.__class__.__name__
            _note("%s: %s failed: %s" % (name, site.LABEL, error), logging.WARNING)
            with _lock:
                _state["errors"] += 1
            complete = None
        with db.connect() as con:
            con.execute("UPDATE sources SET last_checked = datetime('now'), last_error = ?, "
                        "complete = CASE WHEN ? THEN 1 ELSE complete END WHERE id = ?",
                        (error, bool(complete), src["id"]))


def _sync_source(artist_id, name, src, site):
    """Returns True when the history was walked to its end (or caught up)."""
    folder = artist_folder(name)
    with db.connect() as con:
        known = {r[0] for r in con.execute(
            "SELECT remote_key FROM files WHERE artist_id = ?", (artist_id,))}
    for number, page in enumerate(site.pages(src["url"]), 1):
        fresh = [m for m in page if m.remote_key not in known]
        for media in fresh:
            _fetch(artist_id, src["id"], folder, media)
            known.add(media.remote_key)
        # Newest first: once a page holds something already seen, everything
        # older was seen too -- but only after one sync has gone all the way.
        if src["complete"] and len(fresh) < len(page):
            return True
        if number >= MAX_PAGES:
            _note("%s: stopped after %d pages; the next sync goes on." % (name, number))
            return False
    return True


def _fetch(artist_id, source_id, folder, media):
    try:
        part, sha, ext = net.download(media.url, folder, media.mime)
    except Exception as e:
        _note("download failed: %s (%s)" % (media.post_url or media.url, e), logging.WARNING)
        with _lock:
            _state["errors"] += 1
        return
    with db.connect() as con:
        dup = con.execute("SELECT path FROM files WHERE artist_id = ? AND sha256 = ? "
                          "AND path IS NOT NULL", (artist_id, sha)).fetchone()
        if dup and os.path.exists(dup["path"]):
            part.unlink(missing_ok=True)
            path = None
            with _lock:
                _state["duplicates"] += 1
        else:
            path = str(_final_path(folder, media, ext))
            os.replace(part, path)
            with _lock:
                _state["new"] += 1
        con.execute("INSERT OR IGNORE INTO files (artist_id, source_id, remote_key, sha256, "
                    "path, post_url, posted) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (artist_id, source_id, media.remote_key, sha, path,
                     media.post_url, media.posted))


def _final_path(folder, media, ext):
    """<date>_<site>_<id><ext>: sorts by date in any file manager."""
    site = media.remote_key.split(":", 1)[0]
    stem = "%s_%s_%s" % ((media.posted or "")[:10] or "undated", site,
                         re.sub(r"[^A-Za-z0-9_-]", "", media.name)[-24:])
    path = folder / (stem + ext)
    n = 2
    while path.exists():
        path = folder / ("%s_%d%s" % (stem, n, ext))
        n += 1
    return path
