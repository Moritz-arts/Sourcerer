"""The gallery: every source of a card in one stream, newest first, straight
from the sites -- nothing saved, nothing kept once it is closed.

It lists through the same site modules as a sync (pages(), one API page at a
time, only when the page has scrolled near the end), so it costs what a
sync's scan costs and keeps the same limits: one request at a time and random
gaps for a login, a site's pause, the day's budget.

Pictures: most sites' preview hosts are plain CDNs the page loads itself
(Media.thumb / large, sent with no referrer). Those that want a Referer or a
login (pixiv, Gelbooru, forums: Media.preview_headers) are fetched by
Sourcerer -- only for an item a listing handed out, never for a URL a page
names, or any web page could make Sourcerer send the user's logins -- and
kept in memory (MEMORY), never on disk. A file already downloaded shows from
the library. "Download" takes the sync's own path: same names, same
duplicate rules, the card's folder.
"""
import collections
import datetime
import io
import logging
import threading
import time
import uuid

from . import db, imaging, net, sources, sync

log = logging.getLogger(__name__)
MEMORY = 160 << 20           # bytes of fetched pictures kept, the oldest dropped first
IDLE = 900                   # a gallery nobody asked anything of this long is closed
MAX_GALLERIES = 3
PAGE = 60                    # items a page asks for at a time

_lock = threading.Lock()
_galleries = {}
_cache = collections.OrderedDict()       # (gallery, item, size) -> (content type, bytes)
_cached = [0]
_flight = {}                             # (gallery, item, size) -> Event, while it is being fetched


def _when(posted):
    """A post's time as a number to sort by, or None when it has none."""
    try:
        dt = datetime.datetime.fromisoformat((posted or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)).timestamp()


class _Source:
    def __init__(self, row):
        self.row, self.site = row, sources.site_for(row["url"])
        self.label = self.site.LABEL if self.site else row["url"]
        self.listing = None
        self.buffer = collections.deque()
        self.done, self.error = self.site is None, ""
        self.last = None                      # an undated item keeps the time of the one before it
        self.turn = 0                         # when this source last gave an item (see _Gallery.more)

    def fill(self):
        """One more page from the site -- one request, or none while it rests."""
        rest = net.paused(self.row["url"])
        if rest:
            self.done, self.error = True, "rests until %s" % time.strftime("%H:%M", time.localtime(rest[0]))
            return
        try:
            if self.listing is None:
                self.listing = self.site.pages(self.row["url"])
            page = next(self.listing)
        except StopIteration:
            self.done = True
            return
        except Exception as e:
            self.done, self.error = True, net.reason(e)
            log.info("gallery: %s stopped: %s", self.row["url"], self.error)
            return
        for m in page:
            when = _when(m.posted)
            self.last = when if when is not None else self.last
            self.buffer.append((self.last, m))         # None: this source has no dates at all

    def close(self):
        # Ends a gallery-dl process (and frees X's or a forum's turn for a sync).
        if self.listing is not None:
            try:
                self.listing.close()
            except Exception:
                pass


class _Gallery:
    def __init__(self, artist):
        self.id = uuid.uuid4().hex
        self.artist = artist
        self.lock = threading.Lock()
        self.seen = time.monotonic()
        self.items = {}                        # item number -> (_Source, Media)
        self.spoken = 0
        self.keys = set()
        with db.connect() as con:
            rows = con.execute("SELECT * FROM sources WHERE artist_id = ? ORDER BY id", (artist["id"],)).fetchall()
            self.saved = {r["remote_key"]: dict(r) for r in con.execute(
                "SELECT id, remote_key, sha256, path, width FROM files WHERE artist_id = ?", (artist["id"],))}
        self.sources = [_Source(r) for r in rows if sources.site_for(r["url"])]

    def state(self):
        return [{"id": s.row["id"], "label": s.label, "url": s.row["url"],
                 "state": "error" if s.error else "done" if s.done and not s.buffer else "more",
                 "error": s.error} for s in self.sources]

    def more(self, n):
        out = []
        while len(out) < n:
            for s in self.sources:                 # every source's next item is needed to sort
                if not s.buffer and not s.done:
                    s.fill()
            live = [s for s in self.sources if s.buffer]
            if not live:
                if out or all(s.done for s in self.sources):
                    break
                continue                            # a page with nothing to show: ask the sources on
            # A source with no dates (forums) takes the time of the newest dated item waiting; of
            # equal times the source that spoke longest ago goes first. Its items then alternate
            # with the others' instead of coming all first (its +inf once drained every other source).
            dated = [s.buffer[0][0] for s in live if s.buffer[0][0] is not None]
            newest = max(dated) if dated else float("-inf")
            s = max(live, key=lambda s: (newest if s.buffer[0][0] is None else s.buffer[0][0], -s.turn))
            self.spoken += 1
            s.turn = self.spoken
            _when_, m = s.buffer.popleft()
            if m.remote_key in self.keys:           # a post two sources share by id (mirrors)
                continue
            self.keys.add(m.remote_key)
            number = len(self.items) + 1
            self.items[number] = (s, m)
            out.append(self.item(number))
        return out

    def item(self, number):
        s, m = self.items[number]
        d = {"id": number, "source": s.label, "src": s.row["id"], "posted": m.posted, "w": m.width,
             "h": m.height, "video": bool(m.video), "post": m.post_url, "saved": False}
        mine = self.saved.get(m.remote_key)
        proxy = "/api/gallery/%s/%d/" % (self.id, number)
        if m.preview_headers is not None:
            d.update(thumb=proxy + "thumb", large=proxy + "large")
        else:
            d.update(thumb=m.thumb, large=m.large or m.thumb)
        if mine:
            d["saved"] = True
            if mine["path"]:                         # the library's copy: no request at all
                d["large"] = "/api/gallery/file/%d" % mine["id"]
                if mine["width"]:
                    d["thumb"] = "/api/thumb/%d?v=%s" % (mine["id"], (mine["sha256"] or "")[:12])
        return d

    def close(self):
        for s in self.sources:
            s.close()


def _reap():
    now = time.monotonic()
    with _lock:
        old = [g for g in _galleries.values() if now - g.seen > IDLE]
        for g in old:
            _galleries.pop(g.id, None)
    for g in old:
        g.close()
        _forget(g.id)


def open_gallery(artist_id):
    _reap()
    with db.connect() as con:
        artist = con.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
    if not artist:
        raise KeyError(artist_id)
    g = _Gallery(dict(artist))
    with _lock:
        _galleries[g.id] = g
        extra = sorted(_galleries.values(), key=lambda x: x.seen)[:-MAX_GALLERIES]
        for old in extra:
            _galleries.pop(old.id, None)
    for old in extra:
        old.close()
        _forget(old.id)
    return {"gallery": g.id, "name": artist["name"], "sources": g.state()}


def _get(gallery_id):
    with _lock:
        g = _galleries.get(gallery_id)
    if not g:
        raise KeyError(gallery_id)
    g.seen = time.monotonic()
    return g


def more(gallery_id, n=PAGE):
    g = _get(gallery_id)
    with g.lock:                                     # one page at a time per gallery
        items = g.more(max(1, min(int(n), 200)))
        state = g.state()
    return {"items": items, "sources": state,
            "done": all(s.done and not s.buffer for s in g.sources)}


def close(gallery_id):
    with _lock:
        g = _galleries.pop(gallery_id, None)
    if g:
        g.close()
        _forget(g.id)


def _forget(gallery_id):
    with _lock:
        for key in [k for k in _cache if k[0] == gallery_id]:
            _cached[0] -= len(_cache.pop(key)[1])


def picture(gallery_id, number, size):
    """(content type, bytes) of an item's grid picture or large view, fetched
    with the headers its site wants and kept in memory only."""
    g = _get(gallery_id)
    s, m = g.items[number]
    key = (gallery_id, number, size)
    with _lock:
        hit = _cache.get(key)
        if hit:
            _cache.move_to_end(key)
            return hit
    # One fetch per picture: a second request for it (stepping away and back in the
    # large view) waits for the first instead of asking the site -- with a login -- again.
    while True:
        with _lock:
            hit = _cache.get(key)
            if hit:
                _cache.move_to_end(key)
                return hit
            flight = _flight.get(key)
            if flight is None:
                _flight[key] = threading.Event()
                break
        flight.wait(120)
    try:
        url = (m.thumb if size == "thumb" else "") or m.large or m.thumb or m.url
        ctype, data = net.fetch_picture(url, headers=m.preview_headers or None, first=size == "large")
        if size == "thumb" and not m.thumb and ctype.startswith("image/"):
            # A forum gives no small picture: one is made here, in memory.
            data, ctype = imaging.preview(io.BytesIO(data), 400), "image/jpeg"
        with _lock:
            if gallery_id not in _galleries:        # closed while it was on its way: keep nothing
                return ctype, data
            _cache[key] = (ctype, data)
            _cached[0] += len(data)
            while _cached[0] > MEMORY and len(_cache) > 1:
                _cached[0] -= len(_cache.popitem(last=False)[1][1])
    finally:
        with _lock:
            _flight.pop(key).set()
    return ctype, data


def download(gallery_id, number):
    """The item's original into the card's folder, the way a sync would save it."""
    g = _get(gallery_id)
    s, m = g.items[number]
    cur = {"artist_id": g.artist["id"], "new": 0, "duplicates": 0, "failed": 0, "existing": 0,
           "file": "", "size": 0}
    with db.connect() as con:
        src = con.execute("SELECT * FROM sources WHERE id = ?", (s.row["id"],)).fetchone()
    done = sync._fetch(g.artist, src or s.row, s.site, m, cur)
    if not done:
        raise RuntimeError("the download did not go through -- see the activity log")
    with db.connect() as con:
        row = con.execute("SELECT id, remote_key, sha256, path, width FROM files WHERE artist_id = ? "
                          "AND remote_key = ?", (g.artist["id"], m.remote_key)).fetchone()
    if row:
        g.saved[m.remote_key] = dict(row)
    kept = bool(cur["new"] or cur["existing"])         # else the same picture was already there
    if cur["new"]:
        sync.event("done", "Saved from the gallery: %s" % (m.post_url or m.url), g.artist)
    return g.item(number), kept


def _reaper():
    while True:
        time.sleep(60)
        try:
            _reap()
        except Exception:
            log.exception("gallery reaper")


threading.Thread(target=_reaper, daemon=True, name="gallery-reaper").start()
