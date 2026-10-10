"""Runs the sources of artists, downloads what is new, decides which copy of a picture stays.

Artists wait in a queue and are synced one at a time in a background thread;
the window polls status(). Each sync first asks every source what is new,
then downloads it -- so the card can say "87 / 240".

A file is new when its remote key was never seen for the artist: a file the
user deleted from the library is not fetched again. What happens to the same
picture from two sources is the artist's choice:

    keep_all   every source keeps its own copy
    best       one copy, the highest resolution (then the larger file)
    master     the master source's copy wins; elsewhere 'best' applies

Byte-identical files are kept once unless the choice is keep_all. Pictures
are compared only across sources: two similar posts on one site are usually
two versions the artist meant to post.
"""
import collections
import datetime
import logging
import os
import pathlib
import re
import threading

from . import config, db, imaging, net, sources

log = logging.getLogger(__name__)

# The first sync of a source walks its whole history, page by page. A ceiling,
# so an account with years of posts cannot keep a sync running for a day.
MAX_PAGES = int(os.environ.get("SOURCERER_MAX_PAGES", "500"))

_lock = threading.Lock()
_queue = []                    # artist ids waiting
_current = None                # what the running sync is doing, for the window
_worker = None
_cancel = threading.Event()
_state = {"message": "Bereit", "finished": None}
_log = collections.deque(maxlen=400)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def status():
    with _lock:
        return {"running": _worker is not None, "current": dict(_current) if _current else None,
                "queue": list(_queue), "message": _state["message"],
                "finished": _state["finished"], "log": list(_log)}


def _note(message, level=logging.INFO):
    log.log(level, message)
    with _lock:
        _state["message"] = message
        _log.append("%s  %s" % (datetime.datetime.now().strftime("%H:%M:%S"), message))


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


def target_folder(artist, label):
    base = artist_folder(artist["name"])
    return base / safe_name(label) if artist["layout"] == "per_source" else base


# ---- queue ------------------------------------------------------------------

def enqueue(artist_ids=None):
    """Queue artists (all when None). Returns how many were added."""
    with db.connect() as con:
        ids = [r[0] for r in con.execute("SELECT id FROM artists ORDER BY name COLLATE NOCASE")]
    if artist_ids is not None:
        wanted = set(artist_ids)
        ids = [i for i in ids if i in wanted]
    global _worker
    with _lock:
        busy = _current["artist_id"] if _current else None
        added = [i for i in ids if i not in _queue and i != busy]
        _queue.extend(added)
        # Under the same lock the worker clears _worker in when it runs dry, so
        # an artist queued in that moment never waits for a worker that is gone.
        if added and _worker is None:
            _worker = threading.Thread(target=_work, daemon=True, name="sync")
            _worker.start()
    return len(added)


def cancel(artist_id):
    with _lock:
        if artist_id in _queue:
            _queue.remove(artist_id)
            return True
        if _current and _current["artist_id"] == artist_id:
            _cancel.set()
            return True
    return False


def _work():
    global _worker, _current
    while True:
        with _lock:
            if not _queue:
                _worker = None
                _state["finished"] = _now()
                return
            artist_id = _queue.pop(0)
            _cancel.clear()
        try:
            _sync_artist(artist_id)
        except Exception as e:                       # never leave a card stuck as running
            log.exception("sync failed")
            _note("Sync fehlgeschlagen: %s" % e, logging.ERROR)
        finally:
            with _lock:
                _current = None


# ---- one artist ---------------------------------------------------------------

def _sync_artist(artist_id):
    global _current
    with db.connect() as con:
        artist = con.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        if not artist:
            return
        rows = con.execute("SELECT * FROM sources WHERE artist_id = ? ORDER BY id",
                           (artist_id,)).fetchall()
        known = {r[0] for r in con.execute(
            "SELECT remote_key FROM files WHERE artist_id = ?", (artist_id,))}
    master = artist["master_source_id"] if artist["dedupe"] == "master" else None
    # The master first: its copies are then already there when the others come,
    # instead of replacing theirs one by one afterwards.
    srcs = sorted((s for s in rows if sources.site_for(s["url"])), key=lambda s: s["id"] != master)
    cur = {"artist_id": artist_id, "name": artist["name"], "phase": "scan", "done": 0, "total": 0,
           "first": any(not s["complete"] for s in srcs), "new": 0, "duplicates": 0,
           "failed": 0, "file": "", "size": 0, "found": 0}
    with _lock:
        _current = cur
    _note("%s: Quellen werden geprüft" % artist["name"])

    todo, walked = [], {}
    for src in srcs:
        if _cancel.is_set():
            break
        site = sources.site_for(src["url"])
        error = None
        try:
            fresh, walked[src["id"]] = _scan(src, site, known, cur)
            todo += [(src, site, m) for m in fresh]
        except Exception as e:
            error = str(e) or e.__class__.__name__
            _note("%s: %s nicht erreichbar: %s" % (artist["name"], site.LABEL, error), logging.WARNING)
        with db.connect() as con:
            con.execute("UPDATE sources SET last_checked = datetime('now'), last_error = ? "
                        "WHERE id = ?", (error, src["id"]))

    with _lock:
        cur.update(phase="download", total=len(todo))
    failed_sources = set()
    for src, site, media in todo:
        if _cancel.is_set():
            break
        if not _fetch(artist, src, site, media, cur):
            failed_sources.add(src["id"])
        with _lock:
            cur["done"] += 1

    cancelled = _cancel.is_set()
    with db.connect() as con:
        # Complete only after a sync went all the way and got everything: until
        # then the next one walks the whole history again and finds what is missing.
        for sid, ok in walked.items():
            if ok and not cancelled and sid not in failed_sources:
                con.execute("UPDATE sources SET complete = 1 WHERE id = ?", (sid,))
        con.execute("UPDATE artists SET last_sync = ?, last_new = ?, last_failed = ?, "
                    "last_activity = CASE WHEN ? THEN ? ELSE last_activity END WHERE id = ?",
                    (_now(), cur["new"], cur["failed"], cur["new"] > 0, _now(), artist_id))
    _note("%s: %s%d neu, %d Duplikate übersprungen, %d fehlgeschlagen." % (
        artist["name"], "abgebrochen -- " if cancelled else "", cur["new"],
        cur["duplicates"], cur["failed"]))


def _scan(src, site, known, cur):
    """What this source has that is new: (media newest first, walked-to-the-end flag)."""
    fresh, seen = [], set()
    for number, page in enumerate(site.pages(src["url"]), 1):
        new = [m for m in page if m.remote_key not in known and m.remote_key not in seen]
        seen.update(m.remote_key for m in new)
        fresh += new
        with _lock:
            cur["found"] += len(new)
        # Newest first: once a page holds something already seen, everything
        # older was seen too -- but only after one sync has gone all the way.
        if src["complete"] and len(new) < len(page):
            return fresh, True
        if number >= MAX_PAGES:
            _note("%s: nach %d Seiten angehalten, der nächste Sync macht weiter." % (
                site.LABEL, number))
            return fresh, False
        if _cancel.is_set():
            return fresh, False
    return fresh, True


def _fetch(artist, src, site, media, cur):
    folder = target_folder(artist, site.LABEL)
    try:
        part, sha, ext = net.download(media.url, folder, media.mime)
    except Exception as e:
        _note("Download fehlgeschlagen: %s (%s)" % (media.post_url or media.url, e), logging.WARNING)
        with _lock:
            cur["failed"] += 1
        return False
    size = part.stat().st_size
    phash, width, height = imaging.info(part)
    path = _final_path(folder, media, ext)
    with _lock:
        cur.update(file=path.name, size=size)
    keep, replaces = _decide(artist, src, sha, phash, width, height, size)
    with db.connect() as con:
        if keep:
            os.replace(part, path)
            for old in replaces:
                _remove(old["path"])
                con.execute("UPDATE files SET path = NULL WHERE id = ?", (old["id"],))
            with _lock:
                cur["new"] += 1
        else:
            part.unlink(missing_ok=True)
            with _lock:
                cur["duplicates"] += 1
        con.execute("INSERT OR IGNORE INTO files (artist_id, source_id, remote_key, sha256, path, "
                    "post_url, posted, phash, width, height, size) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (artist["id"], src["id"], media.remote_key, sha, str(path) if keep else None,
                     media.post_url, media.posted, phash, width, height, size))
    return True


def _decide(artist, src, sha, phash, width, height, size):
    """(keep the new file?, files it replaces)."""
    if artist["dedupe"] == "keep_all":
        return True, []
    with db.connect() as con:
        rows = [r for r in con.execute(
            "SELECT id, source_id, path, sha256, phash, width, height, size FROM files "
            "WHERE artist_id = ? AND path IS NOT NULL", (artist["id"],)) if os.path.exists(r["path"])]
    if any(r["sha256"] == sha for r in rows):
        return False, []
    if not phash:
        return True, []
    same = [r for r in rows if r["phash"] and r["source_id"] != src["id"]
            and imaging.distance(r["phash"], phash) <= imaging.SIMILAR]
    if not same:
        return True, []
    master = artist["master_source_id"] if artist["dedupe"] == "master" else None
    if master and src["id"] == master:
        return True, same
    if master and any(r["source_id"] == master for r in same):
        return False, []

    def quality(w, h, s):
        return ((w or 0) * (h or 0), s or 0)
    best = max(quality(r["width"], r["height"], r["size"]) for r in same)
    if quality(width, height, size) > best:
        return True, same
    return False, []


def _remove(path):
    """A copy that lost to a better one. Only ever a file Sourcerer itself put there."""
    try:
        os.remove(path)
    except OSError as e:
        log.warning("could not remove %s: %s", path, e)


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
