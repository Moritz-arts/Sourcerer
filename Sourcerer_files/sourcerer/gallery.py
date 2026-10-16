"""The gallery: every source of a card -- or of every card, "All artists" -- in one
stream, newest first, straight from the sites; nothing saved, nothing kept once it
is closed. The page's Browse view is this: the artists on the left, their posts on
the right, a source filter on top.

It lists through the same site modules as a sync (pages(), one API page at a
time, only when the page has scrolled near the end), so it costs what a
sync's scan costs and keeps the same limits: one request at a time and random
gaps for a login, a site's pause, the day's budget.

Speed: the sources are asked at the same time (each in its own lane, so a slow
site -- X through gallery-dl, a forum -- no longer makes the fast ones wait),
and a page that has something to show leaves after SLOW seconds without the
sources that are not ready: their pictures come with the next page. A source
whose waiting pictures run low gets its next page in the background, one page
ahead, so scrolling does not stop at every page. A source whose newest posts are kept
(snapshots.py) shows them at once; the site is checked meanwhile -- the page shows a
spinner on that source's chip until it has been, and a count of new posts it found, which
join when the gallery is opened again. A source the page has switched off
(the filter) is not asked at all. The listings of many cards run on a few threads
(POOL), and a site that gallery-dl reads (X, forums) is asked for one source at a time.

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
import concurrent.futures
import dataclasses
import datetime
import hashlib
import io
import logging
import os
import queue
import random
import threading
import time
import uuid

from . import accounts, db, imaging, net, snapshots, sources, sync

log = logging.getLogger(__name__)
MEMORY = 160 << 20           # bytes of fetched pictures kept, the oldest dropped first
IDLE = 900                   # a gallery nobody asked anything of this long is closed
MAX_GALLERIES = 3
PAGE = 60                    # items a page asks for at a time
SLOW = 2.5                   # seconds the first page waits for a source that is not ready, once something can be shown
SLOW_LATER = 0.8             # ... and every later page: the sources are mid-way, a slow one must not hold the rest up
FAST = 0.3                   # ... when snapshots show the first page at once
SEED_PAGES = 3               # pages a seeded source reads looking for a post its snapshot has, before it gives up on it
SEED_AGE = 7 * 86400         # a snapshot older than this is not shown (its links may have expired: Patreon's thumbnails)
AHEAD = 24                   # a source with fewer pictures waiting than this is asked for its next page already
POOL = 6                     # listings running at once, all galleries together
SERIAL = ("x", "xenforo")    # sites gallery-dl reads: one source at a time (_gdl._busy would turn the rest away)

_lock = threading.Lock()
_galleries = {}
_cache = collections.OrderedDict()       # (gallery, item, size) -> (content type, bytes)
_cached = [0]
_flight = {}                             # (gallery, item, size) -> Event, while it is being fetched
_serial = set()                          # sites with a serial source being listed now
_spaced = {}                             # login site -> (card id, when another card may ask it): All artists
_work = queue.Queue()
_workers = []
CARD_GAP = (5, 12)           # seconds before All artists asks a login site for another card than the last one's


class _Workers:
    """POOL daemon threads that run the listings. (A ThreadPoolExecutor's threads are not daemons:
    closing the window would wait for every fill still queued.)"""

    def submit(self, fn):
        future = concurrent.futures.Future()
        with _lock:
            if len(_workers) < POOL:
                t = threading.Thread(target=self._run, daemon=True, name="gallery-source")
                _workers.append(t)
                t.start()
        _work.put((future, fn))
        return future

    @staticmethod
    def _run():
        while True:
            future, fn = _work.get()
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn())
            except BaseException as e:
                future.set_exception(e)


_pool = _Workers()


def _when(posted):
    """A post's time as a number to sort by, or None when it has none."""
    try:
        dt = datetime.datetime.fromisoformat((posted or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)).timestamp()


class _Source:
    def __init__(self, row, artist):
        self.row, self.site, self.artist = row, sources.site_for(row["url"]), artist
        self.label = self.site.LABEL if self.site else row["url"]
        self.where = net.site_of(row["url"])
        # One source at a time per site where a request goes alone anyway -- gallery-dl's (X, forums:
        # it turns the rest away as busy) and every login's lane: they would only sit in a pool thread.
        key = sources.account_key(row["url"]) if self.site else None
        self.login = bool(key and accounts.logged_in(key))
        self.serial = bool(self.site) and (self.site.KIND in SERIAL or self.login)
        self.asked_at = 0.0                   # when it was last asked: the one asked longest ago goes next
        self.spaced = False                   # All artists: a login site's next card waits (CARD_GAP)
        self.seeded, self.known = False, set()                        # shown from the snapshot already
        self.met = False                      # the live pages have reached a post the snapshot has
        self.live = {}                        # remote_key -> the site's own copy of a post the snapshot showed
        self.checked = False                  # the site has been asked for its first page
        self.pages = 0
        self.new = 0                          # posts the check found that the snapshot did not have
        self.listing = None
        self.buffer = collections.deque()
        self.done, self.error = self.site is None, ""
        self.last = None                      # an undated item keeps the time of the one before it
        self.turn = 0                         # when this source last gave an item (see _Gallery.more)
        self.lock = threading.Lock()          # starts one listing at a time
        self.future = None
        self.closed = False
        self.off = False                      # the page's filter: not asked, not shown

    def running(self):
        return self.future is not None and not self.future.done()

    def loading(self):
        """Its first page is still to come -- what the page's spinner shows. (A later page in flight is not.)"""
        return not self.done and not self.off and not self.checked

    def seed(self):
        """The newest posts of the last look, ready to show before any request."""
        snap = snapshots.load(self.row["id"]) if self.site else None
        if not snap or time.time() - snap.tail > SEED_AGE:
            return
        for m in snap.items:
            when = _when(m.posted)
            self.last = when if when is not None else self.last
            self.buffer.append((self.last, m))
        self.known = {m.remote_key for m in snap.items}
        self.seeded = True

    def start_fill(self):
        """The next page, asked for in the background -- not twice at once, and not while another
        source of a site gallery-dl reads is being listed (it would be turned away as busy)."""
        with self.lock:
            if self.done or self.closed or self.off or self.running():
                return
            if self.serial:
                with _lock:
                    if self.where in _serial:
                        return
                    if self.login and self.spaced:
                        last = _spaced.get(self.where)
                        if last and last[0] != self.artist["id"] and time.monotonic() < last[1]:
                            return             # another card was asked lately: not the next one at once
                    _serial.add(self.where)
            self.asked_at = time.monotonic()
            self.future = _pool.submit(self._run)

    def _run(self):
        try:
            if self.closed or self.off:           # queued behind others while the page moved on
                return
            # One artist open: somebody is waiting for these pages, at the gap of a person browsing.
            # All artists reads many accounts at once: the pace of a scan.
            if self.spaced:
                self.fill()
            else:
                with net.interactive():
                    self.fill()
        finally:
            if self.serial and self.login and self.spaced:
                with _lock:
                    _spaced[self.where] = (self.artist["id"], time.monotonic() + random.uniform(*CARD_GAP))
            if self.serial:
                with _lock:
                    _serial.discard(self.where)

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
            self.done, self.checked = True, True
            return
        except Exception as e:
            self.done, self.error, self.checked = True, net.reason(e), True
            log.info("gallery: %s stopped: %s", self.row["url"], self.error)
            return
        finally:
            if self.closed:
                self._end()
        self.pages += 1
        if self.pages == 1:
            snapshots.save(self.row["id"], page)          # the next opening starts from this
            self.checked = True
        if self.seeded:
            # The snapshot's posts are shown already; their links are renewed as they are handed out.
            self.live.update({m.remote_key: m for m in page if m.remote_key in self.known})
            if not self.met:
                # The live pages have not reached a post the snapshot has: the posts before the first
                # one it has are new -- counted, and kept out of the open gallery (they would push
                # the pictures about); offered when the gallery is opened again. Those after the last
                # one it has are older than all it showed, and go on where it ended.
                at = [i for i, m in enumerate(page) if m.remote_key in self.known]
                if at:
                    self.met = True
                    self.new += at[0]
                    page = [m for m in page[at[-1] + 1:] if m.remote_key not in self.known]
                elif self.pages <= SEED_PAGES:
                    self.new += len(page)        # nothing shared yet: the snapshot is behind by more than a page
                    page = []
                else:
                    self.met = True              # never met: the snapshot is no use, show what comes
            else:
                page = [m for m in page if m.remote_key not in self.known]
        for m in page:
            when = _when(m.posted)
            self.last = when if when is not None else self.last
            self.buffer.append((self.last, m))         # None: this source has no dates at all

    def _end(self):
        # Ends a gallery-dl process (and frees X's or a forum's turn for a sync).
        if self.listing is not None:
            try:
                self.listing.close()
            except Exception:
                pass

    def close(self):
        self.closed = True
        self.done = True            # a closed source has nothing more to give: more() must not wait for it
        self._end()                 # a page still on its way closes it when it comes back (fill)


class _Gallery:
    def __init__(self, artist_id, hidden=()):
        """artist_id: one card, or None for every card (All artists). hidden: the sites the page's
        filter has switched off."""
        self.id = uuid.uuid4().hex
        self.all = not artist_id
        self.lock = threading.Lock()
        self.seen = time.monotonic()
        self.items = {}                        # item number -> (_Source, Media)
        self.spoken = 0
        self.keys = set()
        self.saved = {}                        # (artist id, remote_key) -> the library's row, where there is one
        self.asked = set()                     # ... of these, the ones the library was asked about
        with db.connect() as con:
            artists = {r["id"]: dict(r) for r in con.execute(
                "SELECT * FROM artists" + ("" if self.all else " WHERE id = ?"), () if self.all else (artist_id,))}
            if not artists and not self.all:
                raise KeyError(artist_id)
            rows = con.execute("SELECT * FROM sources ORDER BY artist_id, id").fetchall() if self.all else \
                con.execute("SELECT * FROM sources WHERE artist_id = ? ORDER BY id", (artist_id,)).fetchall()
        self.artist = None if self.all else artists[artist_id]
        self.name = "All artists" if self.all else self.artist["name"]
        self.sources = [_Source(r, artists[r["artist_id"]]) for r in rows
                        if r["artist_id"] in artists and sources.site_for(r["url"])]
        for s in self.sources:
            s.spaced = self.all
            s.off = s.label in hidden
            if not s.off:
                s.seed()

    def start_checks(self):
        """Ask the sources that have not been asked for their first page: the ones that showed a
        snapshot, so the page knows they are up to date (and what is new), and any that could not
        start before (their site's lane was busy, or another card was asked lately)."""
        for s in sorted(self.sources, key=lambda s: s.asked_at):
            if not s.checked and not s.done and not s.off:
                s.start_fill()

    def _library(self, pairs):
        """What the library has of these posts, asked once per post: a downloaded one shows
        its own picture and says so."""
        todo = [p for p in pairs if p not in self.asked]
        for i in range(0, len(todo), 150):
            chunk = todo[i:i + 150]
            marks = ",".join("(?, ?)" for _ in chunk)
            with db.connect() as con:
                for r in con.execute("SELECT id, artist_id, remote_key, sha256, path, width FROM files WHERE "
                                     "(artist_id, remote_key) IN (VALUES %s)" % marks,
                                     [v for p in chunk for v in p]):
                    self.saved[(r["artist_id"], r["remote_key"])] = dict(r)
            self.asked.update(chunk)

    def state(self):
        return [{"id": s.row["id"], "label": s.label, "url": s.row["url"],
                 "artist_id": s.artist["id"], "artist": s.artist["name"], "off": s.off,
                 "loading": s.loading(), "checked": s.checked, "cached": s.seeded, "new": s.new,
                 # Items still waiting are more to show, whatever a later page did (a prefetch that failed).
                 "state": "more" if s.buffer else "error" if s.error else "done" if s.done else "more",
                 "error": s.error} for s in self.sources]

    def _kick(self):
        # In the order they were last asked (never first): a site one source at a time serves its
        # sources in turn, not the first one again and again.
        for s in sorted(self.sources, key=lambda s: s.asked_at):
            if not s.buffer and not s.done and not s.off:
                s.start_fill()

    def more(self, n, off=()):
        for s in self.sources:
            s.off = s.row["id"] in off
        out, deadline = [], None
        # Nothing shown yet and nothing kept to show: wait for the first source (SLOW for the rest).
        # With snapshots to show at once there is nothing to wait for.
        grace = SLOW if not self.items and not any(s.buffer and not s.off for s in self.sources) else \
            (FAST if not self.items else SLOW_LATER)
        while len(out) < n:
            self._kick()
            if out and deadline is None:
                deadline = time.monotonic() + grace
            deadline = self._settle(deadline, grace)
            live = [s for s in self.sources if s.buffer and not s.off]
            if not live:
                if out or all(s.done or s.off for s in self.sources):
                    break
                deadline = None                     # nothing to show yet: wait for the pages on their way
                if not any(s.running() for s in self.sources):
                    time.sleep(0.03)                # (one just ended: ask the sources on, without spinning)
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
            m = s.live.get(m.remote_key, m)
            key = (s.artist["id"], m.remote_key)
            if key in self.keys:                    # a post two sources share by id (mirrors)
                continue
            self.keys.add(key)
            number = len(self.items) + 1
            self.items[number] = (s, m)
            out.append(number)
        self._library([(self.items[n][0].artist["id"], self.items[n][1].remote_key) for n in out])
        self._kick()
        for s in sorted(self.sources, key=lambda s: s.asked_at):     # the next page before it is needed
            if not s.done and not s.off and len(s.buffer) < AHEAD:
                s.start_fill()
        self.start_checks()                          # a seeded source whose turn had not come yet
        return [self.item(n) for n in out]

    def _settle(self, deadline, grace):
        """Wait for the pages on their way: as long as it takes while there is nothing to show,
        and grace seconds from the moment there is. Returns the time to stop waiting at."""
        while any(s.running() and not s.buffer and not s.off for s in self.sources):
            now = time.monotonic()
            if deadline is None and any(s.buffer and not s.off for s in self.sources):
                deadline = now + grace
            if deadline is not None and now >= deadline:
                break
            self._kick()                            # a serial site's next source, as its turn comes
            time.sleep(0.03)
        return deadline

    def item(self, number):
        s, m = self.items[number]
        d = {"id": number, "source": s.label, "src": s.row["id"], "posted": m.posted, "w": m.width,
             "h": m.height, "video": bool(m.video), "post": m.post_url, "saved": False,
             "artist": s.artist["name"], "artist_id": s.artist["id"]}
        mine = self.saved.get((s.artist["id"], m.remote_key))
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


def open_gallery(artist_id=None, hidden=()):
    """A gallery of one card, or -- without an id -- of every card."""
    _reap()
    g = _Gallery(artist_id, set(hidden or ()))
    with _lock:
        _galleries[g.id] = g
        extra = sorted(_galleries.values(), key=lambda x: x.seen)[:-MAX_GALLERIES]
        for old in extra:
            _galleries.pop(old.id, None)
    for old in extra:
        old.close()
        _forget(old.id)
    g.start_checks()
    return {"gallery": g.id, "name": g.name, "all": g.all, "sources": g.state()}


def status(gallery_id):
    """Where the sources of a gallery are: loading, checked, new posts found. Asks nobody."""
    g = _get(gallery_id)
    g.start_checks()                  # a source that could not be asked at the opening (its site was busy) goes on now
    return {"sources": g.state(), "new_posts": sum(s.new for s in g.sources if not s.off),
            "loading": any(s.loading() for s in g.sources)}


def _get(gallery_id):
    with _lock:
        g = _galleries.get(gallery_id)
    if not g:
        raise KeyError(gallery_id)
    g.seen = time.monotonic()
    return g


def more(gallery_id, n=PAGE, off=()):
    """off: the ids of the sources the page's filter has switched off."""
    g = _get(gallery_id)
    off = {int(i) for i in off or ()}
    with g.lock:                                     # one page at a time per gallery
        items = g.more(max(1, min(int(n), 200)), off)
        state = g.state()
    return {"items": items, "sources": state,
            "new_posts": sum(s.new for s in g.sources if not s.off),
            "loading": any(s.loading() for s in g.sources),
            "done": all((s.done and not s.buffer) or s.off for s in g.sources)}


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
    """The item's original into its card's folder, the way a sync would save it."""
    g = _get(gallery_id)
    s, m = g.items[number]
    artist = s.artist
    cur = {"artist_id": artist["id"], "new": 0, "duplicates": 0, "failed": 0, "existing": 0,
           "file": "", "size": 0}
    with db.connect() as con:
        src = con.execute("SELECT * FROM sources WHERE id = ?", (s.row["id"],)).fetchone()
    with _lock:
        seen = _cache.get((gallery_id, number, "large"))
    if seen and m.large and m.large == m.url and m.filename and not m.fetch:
        m = _from_memory(m, *seen)             # the large view already fetched the original: no second request
    # Somebody is waiting for this one: ahead of what waits in the site's lane, no reading break.
    with net.interactive():
        done = sync._fetch(artist, src or s.row, s.site, m, cur)
    if not done:
        raise RuntimeError("the download did not go through -- see the activity log")
    with db.connect() as con:
        row = con.execute("SELECT id, artist_id, remote_key, sha256, path, width FROM files WHERE artist_id = ? "
                          "AND remote_key = ?", (artist["id"], m.remote_key)).fetchone()
    if row:
        g.saved[(artist["id"], m.remote_key)] = dict(row)
    kept = bool(cur["new"] or cur["existing"])         # else the same picture was already there
    if cur["new"]:
        sync.event("done", "Saved from the gallery: %s" % (m.post_url or m.url), artist)
        sync.pending_down(artist["id"], s.row["id"], m.remote_key)    # when a look counted it as waiting: one fewer does
    return g.item(number), kept


def _from_memory(media, ctype, data):
    """The item with a fetch that writes bytes already in hand, the way net.download would
    have: (part file, sha256, extension, server's name)."""
    def fetch(folder, progress):
        folder.mkdir(parents=True, exist_ok=True)
        part = folder / (".%s.part" % os.urandom(6).hex())
        try:
            part.write_bytes(data)
            progress(len(data))
        except BaseException:                # a half-written file is nobody's: as net.download
            part.unlink(missing_ok=True)
            raise
        return part, hashlib.sha256(data).hexdigest(), net.extension(ctype, media.url), ""
    return dataclasses.replace(media, fetch=fetch)


def _reaper():
    while True:
        time.sleep(60)
        try:
            _reap()
        except Exception:
            log.exception("gallery reaper")


threading.Thread(target=_reaper, daemon=True, name="gallery-reaper").start()
