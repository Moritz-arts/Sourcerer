"""The four newest pictures on an artist's card -- before, and without, any download.

A card shows what the artist's sources have newest, not only what was saved:
the first page of each source is listed (the gallery's own way, newest first),
the four newest posts of all of them are picked, and a small copy of each
picture is kept in Userdata/Previews/<artist>/ -- a cache, safe to delete, gone
with the card. A post that is downloaded already shows the library's copy
instead (card_thumbs), so nothing is fetched twice and a fresh download
appears at once, without waiting for the next look at the sites.

Gentle by design: one card at a time in the background, the same polite lanes
as a sync, a site that rests or whose login ran out is skipped, and a card is
looked at again after REFRESH_HOURS only. Nothing here is asked on behalf of
the page: the page only reads what is kept.
"""
import datetime
import hashlib
import io
import logging
import os
import random
import re
import shutil
import threading
import time

from . import accounts, config, db, imaging, net, sources

log = logging.getLogger(__name__)
SHOWN = 4                    # pictures on a card
REFRESH_HOURS = 12           # how old the pictures may get before the sites are asked again
RETRY_HOURS = 1              # after a look that reached no source
SIZE = 400                   # px, the longer side of a kept picture
MAX_TRIES = 8                # pictures asked for, at most, to find SHOWN good ones
NAME = re.compile(r"^[0-9a-f]{16}\.jpg$")

_wake = threading.Event()
_lock = threading.Lock()
_queue = []                  # card ids to look at now, whatever their age


def folder(artist_id):
    return config.PREVIEWS / str(artist_id)


def _order(posted):
    """A post's time as text that sorts: 2026-10-14 12:00:00 (the zone is left out)."""
    return (posted or "")[:19].replace("T", " ")


def card_thumbs(con, artist_id):
    """What a card shows, newest first: [{"src": picture URL}] -- the library's copy of a
    post that is saved, else the kept preview, from the previews and the newest downloads."""
    kept = con.execute("SELECT remote_key, posted, file FROM previews WHERE artist_id = ? ORDER BY pos",
                       (artist_id,)).fetchall()
    keys = [r["remote_key"] for r in kept]
    marks = ",".join("?" * len(keys))
    local = {}
    # Saved copies that the previews name, and the newest downloads: a download newer than every
    # preview shows at once; a preview the library has shows the library's picture.
    for r in con.execute("SELECT id, remote_key, sha256, COALESCE(posted, created) AS at FROM files "
                         "WHERE artist_id = ? AND path IS NOT NULL AND width IS NOT NULL AND "
                         "(remote_key IN (%s) OR id IN (SELECT id FROM files WHERE artist_id = ? "
                         "AND path IS NOT NULL AND width IS NOT NULL ORDER BY COALESCE(posted, created) DESC, "
                         "id DESC LIMIT ?))" % marks, [artist_id] + keys + [artist_id, SHOWN]):
        local[r["remote_key"]] = (_order(r["at"]), "/api/thumb/%d?v=%s" % (r["id"], (r["sha256"] or "")[:12]))
    items = {}
    for r in kept:
        src = local[r["remote_key"]][1] if r["remote_key"] in local else (
            "/api/preview/%d/%s" % (artist_id, r["file"]) if r["file"] else None)
        if src:
            items[r["remote_key"]] = (_order(r["posted"]), src)
    for key, item in local.items():
        items.setdefault(key, item)
    # Equal times (undated posts) keep the order the sites gave: Python's sort is stable.
    ranked = sorted(items.values(), key=lambda x: x[0], reverse=True)
    return [{"src": src} for _at, src in ranked[:SHOWN]]


def _candidates(rows):
    """[(posted, Media)] from the first page of each source that can be asked now."""
    from .sources import LoginRequired
    out, reached = [], 0
    for row in rows:
        site = sources.site_for(row["url"])
        if not site or net.paused(row["url"]):
            continue
        key = sources.account_key(row["url"])
        need, _why = sources.login_need(row["url"])
        # A login that ran out would only be asked again for nothing; one that is needed
        # and missing would fail at once.
        if key and accounts.logged_in(key) and (accounts.load(key) or {}).get("state") == "expired":
            continue
        if need == "required" and not (key and accounts.logged_in(key)):
            continue
        listing = None
        try:
            listing = site.pages(row["url"])
            page = next(listing, [])
        except LoginRequired:
            continue
        except Exception as e:
            log.info("previews: %s: %s", row["url"], net.reason(e))
            continue
        finally:
            if listing is not None:
                try:
                    listing.close()
                except Exception:
                    pass
        reached += 1
        out += [(m.posted, m) for m in page[:SHOWN * 2] if (m.thumb or (m.large and not m.video))]
    return out, reached


def _store(artist_id, media):
    """A small copy of a post's picture in the card's folder; its name, or None."""
    name = hashlib.sha1(media.remote_key.encode()).hexdigest()[:16] + ".jpg"
    path = folder(artist_id) / name
    if path.is_file():
        return name
    ctype, data = net.fetch_picture(media.thumb or media.large, headers=media.preview_headers or None,
                                    limit=8 << 20)
    if not ctype.startswith("image/"):
        return None
    jpeg = imaging.preview(io.BytesIO(data), SIZE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(jpeg)
    os.replace(tmp, path)
    return name


def refresh(artist_id):
    """Look at the sources once and keep the newest pictures. False when no source answered."""
    with db.connect() as con:
        if not con.execute("SELECT 1 FROM artists WHERE id = ?", (artist_id,)).fetchone():
            return False
        rows = con.execute("SELECT * FROM sources WHERE artist_id = ? ORDER BY id", (artist_id,)).fetchall()
        saved = {r[0] for r in con.execute("SELECT remote_key FROM files WHERE artist_id = ? AND path IS NOT NULL "
                                           "AND width IS NOT NULL", (artist_id,))}
    pool, reached = _candidates(rows)
    chosen, seen, tries = [], set(), 0
    for posted, media in sorted(pool, key=lambda x: _order(x[0]), reverse=True):
        if len(chosen) >= SHOWN or tries >= MAX_TRIES:
            break
        if media.remote_key in seen:
            continue
        seen.add(media.remote_key)
        if media.remote_key in saved:               # the library has it: the card shows that
            chosen.append((media, posted, None))
            continue
        tries += 1
        try:
            name = _store(artist_id, media)
        except Exception as e:
            log.info("previews: %s: %s", media.post_url or media.url, net.reason(e))
            continue
        if name:
            chosen.append((media, posted, name))
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now if reached else now - datetime.timedelta(hours=REFRESH_HOURS - RETRY_HOURS)
    with db.connect() as con:
        if not con.execute("SELECT 1 FROM artists WHERE id = ?", (artist_id,)).fetchone():
            shutil.rmtree(folder(artist_id), ignore_errors=True)       # the card went meanwhile
            return False
        if chosen:                                   # a look that found nothing keeps what was there
            con.execute("DELETE FROM previews WHERE artist_id = ?", (artist_id,))
            con.executemany("INSERT INTO previews (artist_id, pos, remote_key, posted, file) VALUES (?, ?, ?, ?, ?)",
                            [(artist_id, i, m.remote_key, posted, name) for i, (m, posted, name) in enumerate(chosen)])
        con.execute("UPDATE artists SET previews_at = ? WHERE id = ?", (stamp.isoformat(), artist_id))
    keep = {name for _m, _p, name in chosen if name} if chosen else None
    if keep is not None and folder(artist_id).is_dir():
        for f in folder(artist_id).iterdir():           # what no card shows any more
            if f.name not in keep:
                f.unlink(missing_ok=True)
    return bool(reached)


def forget(artist_id):
    """The card is gone: its pictures go with it."""
    shutil.rmtree(folder(artist_id), ignore_errors=True)


def soon(artist_id):
    """Look at this card next -- it is new, or its sources changed."""
    with _lock:
        if artist_id not in _queue:
            _queue.append(artist_id)
    _wake.set()


def _due():
    """Cards whose pictures are older than REFRESH_HOURS (or never looked at), the most
    recently active first -- those are the ones somebody looks at."""
    limit = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=REFRESH_HOURS)).isoformat()
    with db.connect() as con:
        return [r[0] for r in con.execute(
            "SELECT id FROM artists WHERE (previews_at IS NULL OR previews_at < ?) AND EXISTS "
            "(SELECT 1 FROM sources WHERE artist_id = artists.id) "
            "ORDER BY COALESCE(last_activity, last_sync, created) DESC", (limit,))]


_tried = {}                  # card id -> when it was last looked at, so a failing one is not hammered


def _next():
    """The card to look at now: one somebody just made or changed, else the stalest."""
    with _lock:
        if _queue:
            return _queue.pop(0)
    for artist_id in _due():
        if time.monotonic() - _tried.get(artist_id, -1e9) > RETRY_HOURS * 3600:
            return artist_id
    return None


def _loop():
    time.sleep(random.uniform(8, 20))            # the window first
    while True:
        _wake.clear()
        try:
            artist_id = _next()
        except Exception:
            log.exception("previews: next")
            artist_id = None
        if artist_id is None:
            _wake.wait(300)
            continue
        _tried[artist_id] = time.monotonic()
        try:
            refresh(artist_id)
        except Exception:
            log.exception("previews: card %d", artist_id)
        _wake.wait(random.uniform(1.5, 3.5))       # a card at a time, not a burst at the start


def start():
    threading.Thread(target=_loop, daemon=True, name="previews").start()
