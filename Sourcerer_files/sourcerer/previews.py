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

from . import accounts, config, db, imaging, net, sources, sync

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
_read = {}                   # login site -> when previews last read it
_gone = {}                   # card id -> how many times it was deleted: an id comes back after a delete
version = 0                  # counts the changes to what cards show; the page reloads its cards when it moves


def _changed():
    global version
    version += 1


def folder(artist_id):
    return config.PREVIEWS / str(artist_id)


def _order(posted):
    """A post's time as something that sorts, zone and all (a pixiv post is +09:00, a
    Bluesky one Z); a post with no date sorts last and keeps the order the sites gave."""
    text = (posted or "").strip()
    for candidate in (text.replace("Z", "+00:00"), text[:19]):
        try:
            dt = datetime.datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return (1, (dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)).timestamp())
    return (0, 0.0)


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
    items, lost = {}, False
    for r in kept:
        if r["remote_key"] in local:
            src = local[r["remote_key"]][1]
        elif r["file"] and (folder(artist_id) / r["file"]).is_file():
            src = "/api/preview/%d/%s" % (artist_id, r["file"])
        else:
            src, lost = None, lost or bool(r["file"])      # the cache was cleared: look again soon
        if src:
            items[r["remote_key"]] = (_order(r["posted"]), src)
    if lost:
        con.execute("UPDATE artists SET previews_at = NULL WHERE id = ? AND previews_at IS NOT NULL", (artist_id,))
    for key, item in local.items():
        items.setdefault(key, item)
    # Equal times (undated posts) keep the order the sites gave: Python's sort is stable.
    ranked = sorted(items.values(), key=lambda x: x[0], reverse=True)
    return [{"src": src} for _at, src in ranked[:SHOWN]]


def _space(where):
    """Another card on the same login site: a pause first, as sync takes (NEXT_CARD) --
    not the next read at once."""
    last = max(_read.get(where, -1e9), (sync._used.get(where) or (None, -1e9))[1])
    wait = random.uniform(*sync.NEXT_CARD) - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)


def _candidates(artist, rows, forced):
    """[(posted, Media)] from the first page of each source that can be asked now. A source
    behind a login is where an account can be locked: it is read only when somebody just made
    or changed the card, or automatic sync is on; not when a sync has downloaded its newest
    posts lately (the card shows those); and spaced like sync's cards."""
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
        where = net.site_of(row["url"])
        if key and accounts.logged_in(key):
            hours = sync.MIN_HOURS.get(where) or sync.MIN_HOURS.get(site.KIND) or 0
            synced = artist["last_sync"] and sync._hours_since(artist["last_sync"].replace(" ", "T") + "+00:00") < hours
            if synced or not (forced or db.get_setting("auto_sync") == "1"):
                continue
            _space(where)
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
            _read[where] = time.monotonic()
            if listing is not None:
                try:
                    listing.close()
                except Exception:
                    pass
        reached += 1
        usable = [m for m in page if m.thumb or (m.large and not m.video)]
        out += [(m.posted, m) for m in usable[:SHOWN * 2]]
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


def refresh(artist_id, forced=False):
    """Look at the sources once and keep the newest pictures. False when no source answered.
    forced: the card is new or was changed -- the one case that reads a login site on request."""
    gone = _gone.get(artist_id, 0)
    with db.connect() as con:
        artist = con.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        if not artist:
            return False
        rows = con.execute("SELECT * FROM sources WHERE artist_id = ? ORDER BY id", (artist_id,)).fetchall()
        saved = {r[0] for r in con.execute("SELECT remote_key FROM files WHERE artist_id = ? AND path IS NOT NULL "
                                           "AND width IS NOT NULL", (artist_id,))}
    pool, reached = _candidates(artist, rows, forced)
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
    # A card with no source left shows nothing from the sites; one whose look found nothing
    # keeps what it had.
    replace = bool(chosen) or not rows
    with db.connect() as con:
        if _gone.get(artist_id, 0) != gone or not con.execute("SELECT 1 FROM artists WHERE id = ?", (artist_id,)).fetchone():
            shutil.rmtree(folder(artist_id), ignore_errors=True)       # the card went meanwhile
            return False
        if replace:
            con.execute("DELETE FROM previews WHERE artist_id = ?", (artist_id,))
            con.executemany("INSERT INTO previews (artist_id, pos, remote_key, posted, file) VALUES (?, ?, ?, ?, ?)",
                            [(artist_id, i, m.remote_key, posted, name) for i, (m, posted, name) in enumerate(chosen)])
        con.execute("UPDATE artists SET previews_at = ? WHERE id = ?", (stamp.isoformat(), artist_id))
    if replace and folder(artist_id).is_dir():
        keep = {name for _m, _p, name in chosen if name}
        for f in folder(artist_id).iterdir():           # what no card shows any more
            if f.name not in keep:
                f.unlink(missing_ok=True)
    if replace:
        _changed()
    return bool(reached)


def forget(artist_id):
    """The card is gone: its pictures go with it -- and a look at it that is on its way
    must not give them to the next card that gets this id."""
    _gone[artist_id] = _gone.get(artist_id, 0) + 1
    shutil.rmtree(folder(artist_id), ignore_errors=True)
    _changed()


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
    """(card, asked for) to look at now: one somebody just made or changed, else the stalest."""
    with _lock:
        if _queue:
            return _queue.pop(0), True
    for artist_id in _due():
        if time.monotonic() - _tried.get(artist_id, -1e9) > RETRY_HOURS * 3600:
            return artist_id, False
    return None, False


def _loop():
    time.sleep(random.uniform(8, 20))            # the window first
    while True:
        _wake.clear()
        try:
            artist_id, forced = _next()
        except Exception:
            log.exception("previews: next")
            artist_id, forced = None, False
        if artist_id is None:
            _wake.wait(300)
            continue
        _tried[artist_id] = time.monotonic()
        try:
            refresh(artist_id, forced)
        except Exception:
            log.exception("previews: card %d", artist_id)
        _wake.wait(random.uniform(1.5, 3.5))       # a card at a time, not a burst at the start


def start():
    threading.Thread(target=_loop, daemon=True, name="previews").start()
