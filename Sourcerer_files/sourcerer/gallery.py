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
join when the gallery is opened again. The page's filter by site only hides: every
source is asked whatever the filter says, so switching a site on or off never costs a
request. A gallery the page has left stays open for IDLE seconds (MAX_GALLERIES of them): the
page shows it again as it was, and its pictures are still in memory. The listings of many
cards run on a few threads (POOL), and a site that gallery-dl reads (X, forums) is asked for
one source at a time.

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
import itertools
import json
import logging
import os
import queue
import random
import re
import threading
import time
import urllib.parse
import uuid

import requests

from . import accounts, db, imaging, net, snapshots, sources, sync

log = logging.getLogger(__name__)
MEMORY = 160 << 20           # bytes of fetched pictures kept, the oldest dropped first
IDLE = 1800                  # a gallery nobody asked anything of this long is closed (the page reopens one after 15 minutes anyway)
MAX_GALLERIES = 8            # the page keeps up to 7 aside beside the one it shows
PAGE = 60                    # items a page asks for at a time
SLOW = 2.5                   # seconds the first page waits for a source that is not ready, once something can be shown
SLOW_LATER = 0.8             # ... and every later page: the sources are mid-way, a slow one must not hold the rest up
FAST = 0.3                   # ... when snapshots show the first page at once
FRESH = 5 * 60               # a snapshot younger than this stands in for a source's first live page: opening an artist again within minutes asks no site
FRESH_LOGIN = 60 * 60        # ... an hour on a cookie login's site (X, pixiv, Patreon, Fanbox, Fantia, forums), where every request is the account's
SEED_PAGES = 3               # pages a seeded source reads looking for a post its snapshot has, before it gives up on it
SEED_AGE = 7 * 86400         # a snapshot older than this is not shown (its links may have expired: Patreon's thumbnails)
OFFLINE_AGE = 30 * 86400     # ... except in All artists on a login site, which is nothing BUT snapshots (see _Source.offline): its links stay good
AHEAD = 24                   # a source with fewer pictures waiting than this is asked for its next page already
POOL = 6                     # listings running at once, all galleries together
SERIAL = ("x", "xenforo", "fanbox", "fantia")    # sites gallery-dl reads: one source at a time (_gdl._busy would turn the rest away)

_lock = threading.Lock()
_galleries = {}
_cache = collections.OrderedDict()       # (gallery, item, size) -> (content type, bytes)
_cached = [0]
_flight = {}                             # (gallery, item, size) -> Event, while it is being fetched
_serial = set()                          # sites with a serial source being listed now
_spaced = {}                             # login site -> (card id, when another card may ask it): All artists
_work = queue.PriorityQueue()           # (priority, order, future, fn): an artist's own gallery before All artists' hundreds of sources
_order = itertools.count()
_workers = []
CARD_GAP = (5, 12)           # seconds before All artists asks a login site for another card than the last one's
WINDOWS = ("0", "7", "14", "30", "90")   # Settings > All artists shows: the days (0: everything)


class _Workers:
    """POOL daemon threads that run the listings. (A ThreadPoolExecutor's threads are not daemons:
    closing the window would wait for every fill still queued.)"""

    def submit(self, fn, priority=0):
        future = concurrent.futures.Future()
        with _lock:
            if len(_workers) < POOL:
                t = threading.Thread(target=self._run, daemon=True, name="gallery-source")
                _workers.append(t)
                t.start()
        _work.put((priority, next(_order), future, fn))
        return future

    @staticmethod
    def _run():
        while True:
            _, _, future, fn = _work.get()
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


def _gif(m):
    """Whether the post's file is a GIF picture (not Mastodon's "gifv", which is a looping video)."""
    if m.video:
        return False
    return (m.mime or "").lower() == "image/gif" or \
        (m.filename or m.url or "").lower().split("?", 1)[0].endswith(".gif")


class _Source:
    def __init__(self, row, artist):
        self.row, self.site, self.artist = row, sources.site_for(row["url"]), artist
        self.label = sources.site_name(row["url"]) if self.site else row["url"]      # the website: a server or forum by its own name
        self.kind = self.site.KIND if self.site else ""
        self.host = sources._host(row["url"])
        self.where = net.site_of(row["url"])
        # One source at a time per site where a request goes alone anyway -- gallery-dl's (X, forums:
        # it turns the rest away as busy) and every login's lane: they would only sit in a pool thread.
        key = sources.account_key(row["url"]) if self.site else None
        self.login = accounts.careful(key)
        self.serial = bool(self.site) and (self.site.KIND in SERIAL or self.login)
        self.asked_at = 0.0                   # when it was last asked: the one asked longest ago goes next
        self.spaced = False                   # All artists: a login site's next card waits (CARD_GAP)
        self.seeded, self.known = False, set()                        # shown from the snapshot already
        self.met = False                      # the live pages have reached a post the snapshot has
        self.live = {}                        # remote_key -> the site's own copy of a post the snapshot showed
        self.checked = False                  # the site has been asked for its first page (or the snapshot is fresh: see seed)
        self.fresh = False                    # shown from a snapshot young enough (FRESH) that the site is not asked until the snapshot's end
        self.pages = 0
        self.new = 0                          # posts the check found that the snapshot did not have
        self.listing = None
        self.skip = 0                         # pages a reopened listing passes over (see fill)
        self.buffer = collections.deque()
        self.done, self.error = self.site is None, ""
        self.last = None                      # an undated item keeps the time of the one before it
        self.turn = 0                         # when this source last gave an item (see _Gallery.more)
        self.lock = threading.Lock()          # starts one listing at a time
        self.future = None
        self.closed = False
        self.since = None                     # All artists with a time window: nothing older is handed out (see _Gallery.since)
        self.offline = False                  # All artists on a login site: shown from the snapshot, never asked (see seed)
        self.alone = False                    # the gallery's only source: its posts are never ordered against another's (net.sole)

    def beyond(self):
        """The next post waiting is older than the window: this source has nothing more to show inside it."""
        return self.since is not None and bool(self.buffer) and self.buffer[0][0] is not None and self.buffer[0][0] < self.since

    def enough(self):
        """The window's end is reached: pages come newest first, so once the last post waiting is older than it,
        nothing newer is left on the site and the next page would only read deeper."""
        return self.since is not None and bool(self.buffer) and self.buffer[-1][0] is not None and self.buffer[-1][0] < self.since

    def running(self):
        return self.future is not None and not self.future.done()

    def loading(self):
        """Its first page is still to come -- what the page's spinner shows. (A later page in flight is not.)"""
        return not self.done and not self.checked

    def seed(self):
        """The newest posts of the last look, ready to show before any request.

        All artists never asks a login site (X, pixiv, Patreon, Fanbox, Fantia, forums): it showed hundreds of accounts to the site on every
        opening, and X's whole day went on it (291 follows) -- what the sites can bear is not known (no limit is published) and the account
        is what gets locked. The posts come from what the looks saved (a sync, Refresh all, an artist opened on its own); Refresh all (F5)
        is what asks the sites, within its share of the day (net.scan_room), and the gallery opens again from the new snapshots."""
        if self.spaced and self.login and self.site:
            self.offline = self.done = self.checked = True
        snap = snapshots.load(self.row["id"]) if self.site else None
        if not snap or time.time() - snap.tail > (OFFLINE_AGE if self.offline and self.kind != "patreon" else SEED_AGE):
            return
        for m in snap.items:
            when = _when(m.posted)
            self.last = when if when is not None else self.last
            self.buffer.append((self.last, m))
        self.known = {m.remote_key for m in snap.items}
        self.seeded = True
        # A look of minutes ago is as good as asking again. The site is asked only when the posts of the snapshot run out (fill starts
        # from its first page then, and what the artist posted meanwhile is counted as new); Refresh on the artist reads it at once.
        # (A forum's snapshot made before its pictures had dates is not: the live page brings them, and sorting needs them -- unless the forum is
        # the gallery's only source: nothing is sorted against it, and every opening would otherwise ask the forum again.)
        if not self.offline and time.time() - snap.fetched < (FRESH_LOGIN if self.login else FRESH) \
                and not (self.kind == "xenforo" and not self.alone and any(not m.posted for m in snap.items)):
            self.fresh = self.checked = True

    def start_fill(self):
        """The next page, asked for in the background -- not twice at once, and not while another
        source of a site gallery-dl reads is being listed (it would be turned away as busy)."""
        with self.lock:
            if self.done or self.closed or self.running():
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
            self.future = _pool.submit(self._run, 1 if self.spaced else 0)

    def _run(self):
        try:
            if self.closed:                       # queued behind others while the page moved on
                return
            # One artist open: somebody is waiting for these pages, at the gap of a person browsing.
            # All artists reads many accounts at once: the pace of a scan.
            if self.spaced:
                self.fill()
            else:
                with net.interactive(alone=self.alone):
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
        self.fresh = False
        rest = net.paused(self.row["url"])
        if rest:
            self.done, self.error = True, "rests until %s" % time.strftime("%H:%M", time.localtime(rest[0]))
            return
        try:
            if self.listing is None:
                self.listing = self.site.pages(self.row["url"])
                for _ in range(self.skip):         # reopened after it was parked: the pages read before are passed over
                    next(self.listing)
                self.skip = 0
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
            self._redate()
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
        if self.spaced and self.kind in SERIAL and self.enough() and not self.closed:
            # A gallery-dl process suspended between pages stays alive (about 40 MB each, still asking the site) -- a few
            # hundred follows left that many behind. The window is reached: park it; "Load older" reopens and passes these pages.
            self._end()
            self.listing, self.skip = None, self.pages

    def _redate(self):
        """The snapshot's posts waiting here were sorted by the dates it had; the live page may know more (a forum's pictures had none
        before): their times are taken from the live copies, so the posts are placed among the other sources' by their real time."""
        if not any(self.live.get(m.remote_key) is not None and _when(self.live[m.remote_key].posted) != w
                   for w, m in self.buffer):
            return
        last, out = None, collections.deque()
        for _, m in list(self.buffer):
            m = self.live.get(m.remote_key, m)
            when = _when(m.posted)
            last = when if when is not None else last
            out.append((last, m))
        self.buffer = out
        if out:
            self.last = last

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
    def __init__(self, artist_id):
        """artist_id: one card, or None for every card (All artists)."""
        self.id = uuid.uuid4().hex
        self.all = not artist_id
        self.lock = threading.Lock()
        self.seen = time.monotonic()
        self.items = {}                        # item number -> (_Source, Media)
        self.spoken = 0
        self.keys = set()
        self.progress = {}                     # item number -> (bytes so far, bytes in all or 0) of a download on its way
        self.told = {}                         # item number -> whether the page was told it is in the library
        self.saved = {}                        # (artist id, remote_key) -> the library's row, where there is one
        self.asked = set()                     # ... of these, the ones the library was asked about
        self.sharp = db.get_setting("grid_quality") != "fast"      # the grid shows the largest rendition, not the small one
        # All artists reads every card, so it only reaches back so far (Settings): a source stops being paged once its posts are older
        # than the window, and "Load older" moves the window back by its own length. One artist is read as far as the page scrolls.
        days = db.get_setting("browse_window")
        self.step = int(days if days in WINDOWS else "7") * 86400 if artist_id is None else 0
        self.since = time.time() - self.step if self.step else None
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
            s.alone = len(self.sources) == 1
            s.since = self.since
            s.seed()

    def older(self):
        """Moves the window back by its length; the sources it had parked go on."""
        if self.since is None:
            return
        self.since -= self.step
        for s in self.sources:
            s.since = self.since

    def window_over(self):
        """Every source has given what the window holds (and some have more beyond it): the page offers 'Load older'."""
        return self.since is not None and any(s.beyond() for s in self.sources) and \
            all((s.done and not s.buffer) or s.beyond() for s in self.sources)

    def start_checks(self):
        """Ask the sources that have not been asked for their first page: the ones that showed a
        snapshot, so the page knows they are up to date (and what is new), and any that could not
        start before (their site's lane was busy, or another card was asked lately). Not the ones
        whose snapshot is fresh (`checked` from the start)."""
        for s in sorted(self.sources, key=lambda s: s.asked_at):
            if not s.checked and not s.done:
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
        return [{"id": s.row["id"], "label": s.label, "kind": s.kind, "host": s.host, "url": s.row["url"],
                 "artist_id": s.artist["id"], "artist": s.artist["name"],
                 "loading": s.loading(), "checked": s.checked, "cached": s.seeded, "offline": s.offline, "fresh": s.fresh, "new": s.new,
                 # Items still waiting are more to show, whatever a later page did (a prefetch that failed).
                 "state": "more" if s.buffer else "error" if s.error else "done" if s.done else "more",
                 "error": s.error} for s in self.sources]

    def _kick(self):
        # In the order they were last asked (never first): a site one source at a time serves its
        # sources in turn, not the first one again and again.
        for s in sorted(self.sources, key=lambda s: s.asked_at):
            if not s.buffer and not s.done:
                s.start_fill()

    def more(self, n):
        out, deadline = [], None
        # Nothing shown yet and nothing kept to show: wait for the first source (SLOW for the rest).
        # With snapshots to show at once there is nothing to wait for.
        grace = SLOW if not self.items and not any(s.buffer for s in self.sources) else \
            (FAST if not self.items else SLOW_LATER)
        while len(out) < n:
            self._kick()
            if out and deadline is None:
                deadline = time.monotonic() + grace
            deadline = self._settle(deadline, grace)
            live = [s for s in self.sources if s.buffer and not s.beyond()]
            if not live:
                if out or all(s.done or s.beyond() for s in self.sources):
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
            if not s.done and len(s.buffer) < AHEAD and not s.enough() and not (s.fresh and s.buffer):     # (a fresh snapshot is shown to its end first)
                s.start_fill()
        self.start_checks()                          # a seeded source whose turn had not come yet
        return [self.item(n) for n in out]

    def _settle(self, deadline, grace):
        """Wait for the pages on their way: as long as it takes while there is nothing to show,
        and grace seconds from the moment there is. Returns the time to stop waiting at."""
        while any(s.running() and not s.buffer for s in self.sources):
            now = time.monotonic()
            if deadline is None and any(s.buffer for s in self.sources):
                deadline = now + grace
            if deadline is not None and now >= deadline:
                break
            self._kick()                            # a serial site's next source, as its turn comes
            time.sleep(0.03)
        return deadline

    def item(self, number):
        s, m = self.items[number]
        d = {"id": number, "source": s.label, "kind": s.kind, "host": s.host, "src": s.row["id"], "info": bool(getattr(s.site, "info", None)), "posted": m.posted, "w": m.width,
             "h": m.height, "video": bool(m.video), "post": m.post_url, "saved": False, "fname": _fname(m),
             "key": m.remote_key,
             "artist": s.artist["name"], "artist_id": s.artist["id"]}
        mine = self.saved.get((s.artist["id"], m.remote_key))
        if mine and not self._there(mine):
            mine = None                              # deleted from the library since: not saved any more
        proxy = "/api/gallery/%s/%d/" % (self.id, number)
        sharp = self.sharp
        gif = _gif(m)
        if m.preview_headers is not None:
            d.update(thumb=proxy + "thumb", large=proxy + "large")
        else:
            d.update(thumb=m.thumb, large=m.large or m.thumb)
        if getattr(s.site, "animation", None) and m.remote_key.endswith("_ugoira"):
            d["anim"] = True                         # the large view plays it; the grid keeps the still
        if gif:
            # A GIF plays: the grid shows the file itself, not the site's still of it.
            animated = d["large"] if m.preview_headers is not None else (m.url or m.large or m.thumb)
            d.update(gif=True, thumb=animated, large=animated)
        # A screen-sized rendition that is not the original file nor the grid's picture: what a tile that
        # the grid's small one cannot fill sharply (Full mode's wide pictures) is sharpened with.
        if not mine and m.large and m.large not in (m.url, m.thumb) and not m.video and not gif:
            d["mid"] = proxy + "mid" if m.preview_headers is not None else m.large
            if sharp:                                # the grid shows it at once: no blocky stage, nothing laid over it
                d["thumb"] = d.pop("mid")
        self.told[number] = bool(mine)
        if mine:
            d["saved"] = True
            if mine["path"]:                         # the library's copy: no request at all
                d["large"] = "/api/gallery/file/%d" % mine["id"]
                if gif:
                    d["thumb"] = d["large"]
                elif mine["width"]:
                    d["thumb"] = "/api/thumb/%d?v=%s%s" % (mine["id"], (mine["sha256"] or "")[:12], "&s=960" if sharp else "")
        return d

    def _there(self, row):
        """Whether the library still has what a files row stands for: its file, or -- a byte-identical duplicate that was
        not kept (no path) -- the file it duplicates. A file the user deleted is no longer 'downloaded'."""
        if row["path"]:
            return os.path.isfile(row["path"])
        if not row["sha256"]:
            return False
        with db.connect() as con:
            return any(r[0] and os.path.isfile(r[0]) for r in con.execute(
                "SELECT path FROM files WHERE sha256 = ? AND path IS NOT NULL", (row["sha256"],)))

    def refresh_saved(self):
        """The library is asked again about every post the page has: {item number: its item} for those whose 'in the
        library' changed since the page last heard (downloaded by a sync meanwhile, or deleted by the user)."""
        pairs = [(s.artist["id"], m.remote_key) for s, m in list(self.items.values())]
        self.saved.clear()
        self.asked.clear()
        self._library(pairs)
        changed = {}
        for number in list(self.items):
            before = self.told.get(number)
            item = self.item(number)
            if before is not None and item["saved"] != before:
                changed[number] = item
        return changed

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


def open_gallery(artist_id=None):
    """A gallery of one card, or -- without an id -- of every card."""
    _reap()
    g = _Gallery(artist_id)
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
    return {"sources": g.state(), "new_posts": sum(s.new for s in g.sources),
            "loading": any(s.loading() for s in g.sources)}


# What an address may end in without being a file's name: a script or a page ("index.php", "image.php", a forum's route) -- every XenForo
# picture was "index.php" in the grid.
NOT_FILES = {"php", "php3", "php5", "phtml", "html", "htm", "shtml", "asp", "aspx", "jsp", "cgi", "pl", "py", "do", "action"}


def _fname(m):
    """The file's name on the site, as far as the listing knows it: the site's own (Media.filename), else the last
    part of the address when that looks like a file, else the post's name (a forum's: the title the uploader gave it, which
    is their file name; pixiv's: 12345_p0)."""
    if m.filename:
        return m.filename
    tail = urllib.parse.unquote(urllib.parse.urlparse(m.url or "").path.rsplit("/", 1)[-1])
    return tail if re.fullmatch(r".{1,200}\.[A-Za-z0-9]{2,5}", tail) and tail.rsplit(".", 1)[1].lower() not in NOT_FILES else (m.name or "")


def saved_changes(gallery_id):
    """See _Gallery.refresh_saved. Asks no site."""
    return _get(gallery_id).refresh_saved()


def info(gallery_id, number):
    """What the site knows of one picture beyond its listing (a forum's title, description, date, author, views), asked when the
    viewer opens it -- one request through the site's own lane, kept for the gallery. {} for a site that has no such thing or
    says nothing; a failure is an error the viewer shows quietly."""
    g = _get(gallery_id)
    s, m = g.items[number]
    ask = getattr(s.site, "info", None)
    if not ask:
        return {}

    def get():
        with net.interactive():
            return ask(m)
    got = _once(gallery_id, (gallery_id, number, "info", ""), lambda: ("application/json", json.dumps(get()).encode()))
    data = json.loads(got[1])
    if data.get("posted"):
        m.posted = data["posted"]                    # the date is known now (the picture's own page: it wins over an estimate): the viewer and the item say so
    return data


def progress(gallery_id):
    """{item number: [bytes so far, bytes in all or 0]} of the downloads on their way. Asks nobody."""
    return {n: list(p) for n, p in dict(_get(gallery_id).progress).items()}


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
            "new_posts": sum(s.new for s in g.sources),
            "loading": any(s.loading() for s in g.sources),
            "done": all(s.done and not s.buffer for s in g.sources),
            "older": g.window_over(), "since": g.since}


def older(gallery_id):
    """The window of All artists moved back (Load older): what the page asks for at the end of the grid."""
    g = _get(gallery_id)
    with g.lock:
        g.older()
    return {"since": g.since}


def close(gallery_id):
    with _lock:
        g = _galleries.pop(gallery_id, None)
    if g:
        g.close()
        _forget(g.id)


_no_animation = {}                       # gallery -> item numbers whose animation failed: not asked again while it is open


def _forget(gallery_id):
    with _lock:
        for key in [k for k in _cache if k[0] == gallery_id]:
            old = _cache.pop(key, None)
            if old:
                _cached[0] -= len(old[1])
        _no_animation.pop(gallery_id, None)


def _kept(gallery_id, key, data):
    """Keep fetched bytes in memory (the oldest dropped first); nothing of a gallery that closed meanwhile."""
    if not data:                                     # (nothing to keep: a None here once poisoned the cache, see _once)
        return
    with _lock:
        if gallery_id not in _galleries:
            return
        old = _cache.pop(key, None)
        if old:
            _cached[0] -= len(old[1])
        _cache[key] = data
        _cached[0] += len(data[1])
        while _cached[0] > MEMORY and len(_cache) > 1:
            gone = _cache.popitem(last=False)[1]
            _cached[0] -= len(gone[1]) if gone else 0


def _once(gallery_id, key, make):
    """make() once per key, kept: a second asker waits for the first instead of asking the site --
    with a login -- again (the grid's picture, then the same one in the large view, stepping away and back)."""
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
        data = make()
        _kept(gallery_id, key, data)           # (make() may answer None: pixiv's animation of a work that is no ugoira)
    finally:
        with _lock:
            _flight.pop(key).set()
    return data


def picture(gallery_id, number, size):
    """(content type, bytes) of an item's grid picture, its screen-sized "mid" or its large view, fetched
    with the headers its site wants and kept in memory only. Kept by address, not by size: a site whose
    grid picture is the viewer's picture (a booru's sample) is asked once."""
    g = _get(gallery_id)
    s, m = g.items[number]
    thumb = size == "thumb"
    animate = getattr(s.site, "animation", None)
    if size == "large" and animate and number not in _no_animation.get(gallery_id, ()):
        # a site's animation (pixiv's ugoira) plays in the large view. It answers None for a work that is no ugoira, and an
        # animation that failed is not asked for again each time the picture is opened: pixiv's ugoira_meta is a request.
        try:
            got = _once(gallery_id, (gallery_id, number, "animation", ""), lambda: animate(m))
            if got:
                return got
            _no_animation.setdefault(gallery_id, set()).add(number)
        except Exception as e:
            _no_animation.setdefault(gallery_id, set()).add(number)
            log.info("animation of %s: %s", m.post_url, net.reason(e))
    url = (m.thumb if thumb else "") or m.large or m.thumb or m.url
    if _gif(m) and m.url:
        url = m.url                                  # the GIF itself, for the grid and the viewer alike

    def get(address):
        # No retries for an answer (a refusal, a pause), but a dropped connection or a timeout is
        # asked once more: one hiccup must not leave a hole in the grid.
        try:
            return net.fetch_picture(address, headers=m.preview_headers or None, first=size == "large")
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(0.8)
            return net.fetch_picture(address, headers=m.preview_headers or None, first=size == "large")

    def fetch(address):
        return _once(gallery_id, (gallery_id, number, address, ""), lambda: get(address))

    try:
        data = fetch(url)
    except Exception:
        # A grid picture that is not there (a rendition the site does not make): the viewer's one will do.
        fallback = m.large or m.url
        if not thumb or not m.thumb or not fallback or fallback == url:
            raise
        data = fetch(fallback)
    if thumb and not m.thumb and data[0].startswith("image/") and not _gif(m):
        # A forum gives no small picture: one is made here, in memory, from the original the viewer will want too.
        return _once(gallery_id, (gallery_id, number, url, "small"),
                     lambda: ("image/jpeg", imaging.preview(io.BytesIO(data[1]), 400)))
    return data


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
        seen = _cache.get((gallery_id, number, m.large, ""))
    if seen and m.large and m.large == m.url and m.filename and not m.fetch:
        m = _from_memory(m, *seen)             # the large view already fetched the original: no second request
    # Somebody is waiting for this one: ahead of what waits in the site's lane, no reading break.
    g.progress[number] = (0, 0)
    try:
        with net.interactive(), net.watching(lambda done, total: g.progress.__setitem__(number, (done, total))):
            done = sync._fetch(artist, src or s.row, s.site, m, cur)
    finally:
        g.progress.pop(number, None)
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


# ---- the Artists view: the newest posts of a card, from what the looks saved ----------------------------------------------------

OVERVIEW = 8                 # pictures an artist shows in the Artists view
SNAP_MEMORY = 40 << 20       # bytes of those small pictures kept in memory (never on disk)
_snap = collections.OrderedDict()       # (source id, remote key) -> (content type, bytes)
_snapped = [0]
_snap_flight = {}


def overview(artist_ids):
    """{artist id: [{"thumb", "post", "date"}]}: the newest OVERVIEW (8) posts of each card across all its sources, from the snapshots
    the looks saved (nothing is asked of any site here), a picture of the library where the post is downloaded already, and --
    for an artist the looks never saw -- what the library has. A snapshot is not shown past the age its links keep good (the
    same as All artists: OFFLINE_AGE, Patreon's thumbnails SEED_AGE)."""
    ids = [int(i) for i in artist_ids][:60]
    out = {i: [] for i in ids}
    if not ids:
        return out
    with db.connect() as con:
        rows = con.execute("SELECT id, artist_id, url FROM sources WHERE artist_id IN (%s) ORDER BY id" % ",".join("?" * len(ids)), ids).fetchall()
        for artist_id in ids:
            found = []                                       # (when, source id, Media)
            for r in rows:
                if r["artist_id"] != artist_id:
                    continue
                site = sources.site_for(r["url"])
                snap = snapshots.load(r["id"]) if site else None
                if not snap or time.time() - snap.tail > (SEED_AGE if site.KIND == "patreon" else OFFLINE_AGE):
                    continue
                found += [(_when(m.posted), r["id"], m) for m in snap.items if m.thumb or m.large or m.url]
            found.sort(key=lambda t: t[0] if t[0] is not None else float("-inf"), reverse=True)
            top, seen = [], set()
            for when, sid, m in found:
                if m.remote_key in seen:
                    continue
                seen.add(m.remote_key)
                top.append((sid, m))
                if len(top) == OVERVIEW:
                    break
            have = {}
            if top:                                          # posts the library has: its own picture, no request at all
                marks = ",".join("?" * len(top))
                for f in con.execute("SELECT id, remote_key, path FROM files WHERE artist_id = ? AND path IS NOT NULL AND remote_key IN (%s)" % marks,
                                     [artist_id] + [m.remote_key for _, m in top]):
                    if f["path"] and os.path.isfile(f["path"]):
                        have[f["remote_key"]] = f["id"]
            items = [{"thumb": "/api/thumb/%d?s=480" % have[m.remote_key] if m.remote_key in have else
                      "/api/snap/%d/thumb?k=%s" % (sid, urllib.parse.quote(m.remote_key, safe="")),
                      "post": m.post_url or "", "date": m.posted or ""} for sid, m in top]
            if len(items) < OVERVIEW:                        # a card the looks never saw: what it has downloaded
                keys = {m.remote_key for _, m in top}
                for f in con.execute("SELECT id, remote_key, posted, post_url, path FROM files WHERE artist_id = ? AND path IS NOT NULL "
                                     "ORDER BY posted DESC, id DESC LIMIT ?", (artist_id, OVERVIEW * 3)):
                    if len(items) == OVERVIEW:
                        break
                    if f["remote_key"] in keys or not f["path"] or not os.path.isfile(f["path"]):
                        continue
                    keys.add(f["remote_key"])
                    items.append({"thumb": "/api/thumb/%d?s=480" % f["id"], "post": f["post_url"] or "", "date": f["posted"] or ""})
            out[artist_id] = items
    return out


def snapshot_picture(source_id, key):
    """(content type, bytes) of one post of a snapshot, small, for the Artists view -- fetched the way the gallery does (the headers
    its site wants, no login to a picture host) and kept in memory only. The page names the post by its remote_key, never by an
    address: any page could otherwise make Sourcerer fetch what it likes."""
    ck = (source_id, key)
    while True:
        with _lock:
            hit = _snap.get(ck)
            if hit:
                _snap.move_to_end(ck)
                return hit
            flight = _snap_flight.get(ck)
            if flight is None:
                _snap_flight[ck] = threading.Event()
                break
        flight.wait(60)
    try:
        snap = snapshots.load(source_id)
        m = next((x for x in snap.items if x.remote_key == key), None) if snap else None
        if m is None:
            raise KeyError(key)
        url = m.thumb or m.large or m.url
        try:
            ctype, data = net.fetch_picture(url, headers=m.preview_headers or None)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(0.8)
            ctype, data = net.fetch_picture(url, headers=m.preview_headers or None)
        if ctype.startswith("image/") and (not m.thumb or _gif(m)):
            ctype, data = "image/jpeg", imaging.preview(io.BytesIO(data), 480)      # (an original, or a GIF: a small still)
        elif not ctype.startswith("image/"):
            raise RuntimeError("no still picture for this post")
        with _lock:
            _snap[ck] = (ctype, data)
            _snapped[0] += len(data)
            while _snapped[0] > SNAP_MEMORY and len(_snap) > 1:
                _snapped[0] -= len(_snap.popitem(last=False)[1][1])
        return ctype, data
    finally:
        with _lock:
            _snap_flight.pop(ck).set()


def _reaper():
    while True:
        time.sleep(60)
        try:
            _reap()
        except Exception:
            log.exception("gallery reaper")


threading.Thread(target=_reaper, daemon=True, name="gallery-reaper").start()
