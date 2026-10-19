"""Runs the sources of artists, downloads what is new, decides which copy of a picture stays.

Artists wait in a queue and are handled one at a time in a background thread;
the window polls status(). There are two jobs, kept apart:

    sync      (mode "refresh") looks at the newest posts of every source, keeps what it
              saw (snapshots.py) and counts what is new and not downloaded (artists.pending).
              Nothing is downloaded -- unless the card has auto-download on: then the sync
              goes on to download what is new.
    download  (mode "download") asks every source what is new, walking its history as
              far as it takes, then downloads it -- several files at once, within each
              site's limits (net.py) -- so the card can say "87 / 240" and the activity
              bar a speed.

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
import glob
import hashlib
import json
import logging
import os
import pathlib
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import accounts, config, db, imaging, net, snapshots, sources

log = logging.getLogger(__name__)

# The first sync of a source walks its whole history, page by page. A ceiling,
# so an account with years of posts cannot keep a sync running for a day.
MAX_PAGES = int(os.environ.get("SOURCERER_MAX_PAGES", "500"))
AVATAR_DAYS = 7              # how often a profile picture is looked for again
ACCOUNT_HOURS = (5, 9)       # how often the saved logins are checked, drawn anew each time
CHECKED_HOURS = 12           # a login checked this recently is not asked again at a start
# Automatic syncs come no closer than this to a site where an account can be
# locked (a sync started by hand does not wait).
MIN_HOURS = {"x": 12, "pixiv": 6, "patreon": 6, "xenforo": 12, "fanbox": 6, "fantia": 6}
# Seconds before the next card asks a site where a cookie login can get banned (pixiv, X, Patreon, a forum) the last one
# used -- Settings > Sync decides how careful. Token logins (Mastodon, Bluesky) are not spaced: the lane paces them.
LOGIN_GAPS = {"careful": (15, 60), "normal": (10, 30), "fast": (3, 15)}
FOCUS_GAP = (4, 10)          # ... for the card somebody has opened in Browse: they are waiting
PICK_FROM = 40               # the next card is the first of this many waiting ones whose sites are not cooling down
GIVE_UP = 3                  # syncs a file may fail before its source completes without it

_lock = threading.Lock()
_save = threading.Lock()     # deciding and saving happen one file at a time
_queue = []                  # artist ids waiting
_auto = set()                # of those, queued by the automatic sync
_starting = set()            # popped by a worker, not in _running yet: busy all the same (merge asks, _pick avoids its sites)
_only = {}                   # artist id -> ids of the only sources a queued sync asks (Browse: download these)
_modes = {}                  # artist id -> "refresh" or "download" for a queued job (none: the card's auto-download decides)
_followup = {}               # artist id -> sources (None: all) of a download asked for while the card's own job could not take it
PENDING_KEYS = 400           # posts per source whose keys are kept as "waiting for a download"
REFRESH_ITEMS = 120          # a sync (refresh) reads a source's newest pages until it has this many posts
REFRESH_PAGES = 4            # ... or this many pages
_used = {}                   # careful login site -> (artist id, when its last card was done with it)
_focused = set()             # queued cards that Browse opened: they go first, and wait less
WORKERS = 3                  # cards worked on at once -- only cards that share no site where requests must go one at a time
GDL_KINDS = ("x", "xenforo", "fanbox", "fantia")      # read through gallery-dl: one listing per site at a time (_gdl._busy)
_running = {}                # artist id -> what its sync is doing, for the window (in the order they began)
_cancels = {}                # artist id -> the Event that cancels its running sync
_workers = set()             # the worker threads
_state = {"finished": None}
_log = collections.deque(maxlen=300)
_speed = collections.deque()  # (time, bytes) of the last seconds


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def status():
    """current: the card that began first and still runs; active: all of them (several can run at once)."""
    with _lock:
        active = [dict(c) for c in _running.values()]
        speed = _rate()
        for c in active:
            c["speed"] = speed
        return {"running": bool(_workers or _running), "current": active[0] if active else None, "active": active,
                "queue": list(_queue), "finished": _state["finished"], "log": list(_log)}


def event(kind, text, artist=None, **counts):
    """One line of the activity log, with what the window needs to draw it."""
    level = {"error": logging.ERROR, "warn": logging.WARNING}.get(kind, logging.INFO)
    log.log(level, "%s%s", (artist["name"] + ": ") if artist else "", text)
    with _lock:
        _log.append(dict(counts, kind=kind, text=text, time=_now(),
                         artist=artist["name"] if artist else "",
                         artist_id=artist["id"] if artist else None))


def _count_bytes(n):
    with _lock:
        _speed.append((time.monotonic(), n))


def _rate():
    """Bytes per second over the last five seconds. Called under _lock."""
    cut = time.monotonic() - 5
    while _speed and _speed[0][0] < cut:
        _speed.popleft()
    return int(sum(n for _, n in _speed) / 5)


# ---- where files go -----------------------------------------------------------

def library():
    return db.get_setting("library") or str(config.DEFAULT_LIBRARY)


def safe_name(name):
    """A file or folder name every system accepts: no reserved characters, no trailing dot."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(".")
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM\d|LPT\d)(\..*)?", name):
        name = "_" + name
    return name[:120] or "Unnamed"


def artist_folder(artist, lib=None):
    """The card's own folder if one was chosen, else <library>/<name>. lib: library(), for a caller
    that asks for many cards."""
    if artist["folder"]:
        return pathlib.Path(artist["folder"])
    return pathlib.Path(lib or library()) / safe_name(artist["name"])


def target_folder(artist, label):
    base = artist_folder(artist)
    return base / safe_name(label) if artist["layout"] == "per_source" else base


def _final_path(folder, media, ext, server_name, posted):
    """The file's own name where the site has one; <date>_ in front if Settings say so."""
    name = safe_name(server_name or media.filename or media.name)
    stem, own = os.path.splitext(name)
    # Keep an extension the name already has; add the one the content says.
    # Up to 12 characters: artists attach .swatches, .procreate, .brushset files.
    if not own or len(own) > 12 or not re.fullmatch(r"\.[A-Za-z0-9]+", own):
        stem, own = name, ext
    if db.get_setting("filenames") == "dated" and posted:
        stem = "%s_%s" % (posted[:10], stem)
    path = folder / (stem + own)
    n = 2
    while path.exists():
        path = folder / ("%s_%d%s" % (stem, n, own))
        n += 1
    return path


# ---- queue ------------------------------------------------------------------

def next_card():
    return LOGIN_GAPS.get(db.get_setting("login_gap"), LOGIN_GAPS["normal"])


def enqueue(artist_ids=None, auto=False, only=None, mode=None, everyone=False, order=None):
    """Queue artists. None: a sweep -- the cards with auto-download (Automatic sync, the scan at start: comparing what a
    card finds with its library is what costs the time, so only those do), or with everyone every card, listed ones
    too (Refresh all, which somebody asked for): the cards with auto-download as they are, every other one only has
    its newest page looked at for posts it did not have at the last look (mode "scan": no comparison with the
    library). order: ids in the order the list shows them, which a sweep follows. Returns
    how many were added. only: the ids of the
    sources to ask -- the rest of the card is left alone this time (Browse: download what
    the filter shows). mode: "download" to download, "refresh" to only look; none lets the
    card's auto-download decide (a sync that downloads what it finds, or not).

    The longest unsynced first, in a random order among equals: not the same
    cards in the same order every day."""
    with db.connect() as con:
        # Cards only listed (made from a login's follows) are in nobody's sweep: Sync all and the
        # automatic sync leave them alone. Asking for one -- by name -- takes it into the routine.
        rows = con.execute(
            "SELECT id, auto_download FROM artists" +
            ("" if artist_ids is not None or everyone else " WHERE listed = 0 AND auto_download = 1") +
            " ORDER BY COALESCE(last_sync, ''), RANDOM()").fetchall()
        ids, downloads = [r[0] for r in rows], {r[0] for r in rows if r[1]}
        if artist_ids is not None and not auto:
            con.executemany("UPDATE artists SET listed = 0 WHERE id = ?", [(i,) for i in artist_ids])
    if artist_ids is not None:
        wanted = set(artist_ids)
        ids = [i for i in ids if i in wanted]
    elif order:
        place = {i: n for n, i in enumerate(order) if isinstance(i, int)}
        ids.sort(key=lambda i: place.get(i, len(place)))        # (stable: the rest keeps its order)
    followed = 0
    with _lock:
        # A download asked for while the same card is only being looked at follows it.
        follows = {i for i, c in _running.items() if mode == "download" and c.get("mode") in ("refresh", "scan")}
        added = [i for i in ids if i not in _queue and ((i not in _running and i not in _starting) or i in follows)]
        _queue.extend(added)
        for i in added:
            if only:
                _only[i] = set(only)
            else:
                _only.pop(i, None)
            if mode:
                _modes[i] = mode
            elif everyone and artist_ids is None and i not in downloads:
                _modes[i] = "scan"                 # a card that does not download is only looked at
            else:
                _modes.pop(i, None)
        # Asked for again while it waits. A download for the whole card covers whatever waits; a
        # restricted one joins a restricted download. Nothing else changes a wait: a look is no reason
        # to widen a restricted download (Browse's filter said which sources), and a restricted
        # download must not make a card's sync a download of every source.
        for i in ids:
            if i in added:
                continue
            if i in _queue:
                if not only and mode == "download":
                    _only.pop(i, None)
                    _modes[i] = "download"
                    continue
                if only and i in _only:
                    _only[i] |= set(only)
                    if mode == "download":
                        _modes[i] = "download"
                    continue
                if mode == "download" and _modes.get(i) == "download" and i not in _only:
                    continue                           # a download of the whole card waits: it covers this
            if mode == "download":
                # A download the wait or the running job cannot take (a look, a restricted download of
                # other sources): it comes after them -- asked for, not lost.
                followed += 1
                _followup[i] = None if (not only or (i in _followup and _followup[i] is None)) else \
                    (_followup.get(i) or set()) | set(only)
        if auto:
            _auto.update(added)
        else:                              # somebody asked: not the careful automatic kind any more
            _auto.difference_update(added if only else ids)     # (a restricted ask of a queued card changes nothing else)
        # Under the same lock a worker leaves in when it runs dry, so an artist queued in that
        # moment never waits for a worker that is gone.
        _spawn()
    return len(added) + followed


def _unqueue(artist_id):
    """Take a card off the waiting list (the lock is held). True when it was on it."""
    if artist_id not in _queue:
        return False
    _queue.remove(artist_id)
    _auto.discard(artist_id)
    _focused.discard(artist_id)
    _only.pop(artist_id, None)
    _modes.pop(artist_id, None)
    _followup.pop(artist_id, None)
    return True


def focus(artist_id):
    """Browse opened this artist: if it waits for its turn it comes next (the card being worked on is finished first)
    and its sites' pauses are the short ones. True when it moved up."""
    with _lock:
        if artist_id not in _queue:
            return False
        _focused.add(artist_id)
        if _queue[0] != artist_id:
            _queue.remove(artist_id)
            _queue.insert(0, artist_id)
        return True


def _exclusive(url):
    """The site where this source must be read by one card at a time: a cookie login's (an account is what gets banned,
    and its gap between cards is kept per site) and one gallery-dl reads (its lock turns a second listing away). The other
    sites' lanes (net) pace whoever comes."""
    if not sources.site_for(url):
        return None
    if accounts.careful(sources.account_key(url)) or sources.kind_of(url) in GDL_KINDS:
        return net.site_of(url)
    return None


def _pick():
    """The next card to work on, taken off the queue (the lock is held), or None when every card that waits needs a site
    that another running card has. The card Browse opened first; else the first of the first few whose cookie-login
    sites are not cooling down from the last card -- so a card on pixiv does not hold up the Bluesky ones behind it --
    else, when nothing else runs, whichever will be ready soonest."""
    head = _queue[:PICK_FROM]
    now = time.monotonic()
    cooling = {i: 0.0 for i in head}
    sites = {i: set() for i in head}
    with db.connect() as con:
        rows = con.execute("SELECT artist_id, url FROM sources WHERE artist_id IN (%s)" % ",".join("?" * len(head)), head).fetchall()
        busy, going = set(), list(set(_running) | _starting)       # (a card just picked is not in _running yet)
        if going:
            for aid, url in con.execute("SELECT artist_id, url FROM sources WHERE artist_id IN (%s)" % ",".join("?" * len(going)), going):
                busy.add(_exclusive(url))
    for aid, url in rows:
        where = _exclusive(url)
        if where:
            sites[aid].add(where)
            used = _used.get(where)
            if used and used[0] != aid:
                cooling[aid] = max(cooling[aid], next_card()[0] - (now - used[1]))
    free = [i for i in head if not sites[i] & busy]
    if not free:
        return None
    for i in free:                                    # the card somebody opened: before the rest
        if i in _focused:
            _queue.remove(i)
            return i
    ready = [i for i in free if cooling[i] <= 0]
    chosen = ready[0] if ready else (min(free, key=lambda i: cooling[i]) if not (_running or _starting) else None)
    if chosen is not None:
        _queue.remove(chosen)
    return chosen


def cancel(artist_id):
    with _lock:
        if _unqueue(artist_id):
            return True
        if artist_id in _cancels:                     # running, or just picked
            _followup.pop(artist_id, None)
            _cancels[artist_id].set()
            return True
    return False


def _cancelled(cur):
    """Whether the sync that `cur` belongs to was cancelled."""
    event_ = _cancels.get(cur.get("artist_id"))
    return bool(event_ and event_.is_set())


def _spawn():
    """Workers for the cards that wait, up to WORKERS (the lock is held). A worker that finds nothing it may start while
    others run leaves; the ones that run pick the next card when they are done."""
    for _ in range(min(WORKERS - len(_workers), len(_queue))):
        t = threading.Thread(target=_work, daemon=True, name="sync")
        _workers.add(t)
        t.start()


def _work():
    me = threading.current_thread()
    while True:
        with _lock:
            artist_id = _pick() if _queue else None
            if artist_id is None:
                _workers.discard(me)
                if not _workers and not _running:
                    _state["finished"] = _now()
                return
            _starting.add(artist_id)
            auto = artist_id in _auto
            only = _only.pop(artist_id, None)
            mode = _modes.pop(artist_id, None)
            _auto.discard(artist_id)
            cancel = _cancels[artist_id] = threading.Event()
        try:
            _sync_artist(artist_id, auto, only, mode)
        except Exception as e:                       # never leave a card stuck as running
            log.exception("sync failed")
            event("error", "Sync failed: %s" % net.reason(e))
        finally:
            with _lock:
                _running.pop(artist_id, None)
                _cancels.pop(artist_id, None)
                _starting.discard(artist_id)
                later = _followup.pop(artist_id, False)
        if later is not False and not cancel.is_set():      # a download asked for meanwhile follows the job
            enqueue([artist_id], only=later, mode="download")


def scheduler():
    """Automatic sync: every card, every few hours, while Sourcerer runs.
    And a look at every saved login, right at the start and then every
    ACCOUNT_HOURS, so a login that ran out is shown before a sync needs it."""
    def run():
        time.sleep(random.uniform(20, 60))    # the window first, and not the start's own second
        check_accounts_at_start()
        threading.Thread(target=backfill_avatars, daemon=True, name="avatar-addresses").start()
        if db.get_setting("scan_on_start") == "1":           # as Refresh: a card with auto-download downloads what it finds
            try:
                if enqueue(auto=True):
                    event("info", "Looking for new posts, as at every start")
            except Exception:
                log.exception("scan at start")
        next_check = time.monotonic() + random.uniform(*ACCOUNT_HOURS) * 3600
        while True:
            time.sleep(60)
            _upgrade_gallery_dl()
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + random.uniform(*ACCOUNT_HOURS) * 3600
                try:
                    check_accounts(spread=True, fresh_hours=CHECKED_HOURS / 2)
                except Exception:
                    log.exception("account check")
            try:
                if db.get_setting("auto_sync") != "1":
                    continue
                now = time.time()
                if now >= _next_auto(now):
                    hours = db.setting_int("auto_hours", 1, 168)
                    # Not every n hours on the dot: a regular robot is the easiest to spot.
                    db.set_setting("next_auto", str(now + hours * 3600 * random.uniform(0.85, 1.2)))
                    db.set_setting("last_auto", datetime.datetime.now(datetime.timezone.utc).isoformat())
                    time.sleep(random.randint(0, 180))
                    if enqueue(auto=True):
                        event("info", "Automatic sync started")
            except Exception:
                log.exception("scheduler")
    threading.Thread(target=run, daemon=True, name="scheduler").start()


def backfill_avatars():
    """Cards made by hand that do not know where their profile picture is (v0.32 kept the file, not the address) or what
    their profiles name: one card at a time, a few seconds apart, through a source on a site that is no login risk -- the
    rest learn it at their next sync. Cards of a follow list got both from the list."""
    with db.connect() as con:
        ids = [r[0] for r in con.execute("SELECT id FROM artists WHERE listed = 0 AND avatar_url IS NULL "
                                         "AND avatar_checked IS NULL ORDER BY id")]
    for artist_id in ids:
        with db.connect() as con:
            rows = con.execute("SELECT id, url FROM sources WHERE artist_id = ? ORDER BY id", (artist_id,)).fetchall()
        rows = [r for r in rows if sources.site_for(r["url"]) and not accounts.careful(sources.account_key(r["url"]))
                and not net.paused(r["url"])]
        for row in rows:
            try:
                info = sources.profile(row["url"]) or {}
            except Exception as e:
                log.info("no profile from %s: %s", row["url"], net.reason(e))
                continue
            _note_links(row["id"], info)
            if info.get("avatar"):
                _set_avatar(artist_id, info["avatar"], info.get("avatar_headers"))
                break
        if rows:
            with db.connect() as con:
                con.execute("UPDATE artists SET avatar_checked = COALESCE(avatar_checked, ?) WHERE id = ?", (_now(), artist_id))
        time.sleep(random.uniform(4, 9))


def _next_auto(now):
    """When the next automatic sync is due (Unix time)."""
    try:
        return float(db.get_setting("next_auto") or "")
    except ValueError:
        pass
    last = db.get_setting("last_auto") or ""      # before next_auto existed
    if not last:
        return now
    hours = db.setting_int("auto_hours", 1, 168)
    return datetime.datetime.fromisoformat(last).timestamp() + hours * 3600


def _paused_event(site, until, why):
    event("warn", "%s rests until %s: %s" % (net.name_of(site), time.strftime("%H:%M", time.localtime(until)), why))


net.PAUSED.append(_paused_event)


# ---- logins ---------------------------------------------------------------------------

def _login_ran_out(key, label, stamp=None):
    was = (accounts.load(key) or {}).get("state")
    accounts.mark(key, False, "the site no longer accepts the login", stamp)
    if was != "expired" and (accounts.load(key) or {}).get("state") == "expired":   # once, not on every sync
        event("error", "%s: the login has run out -- log in again under Manage Accounts" % label)


def _still_logged_in(key):
    """True / False, or None when there is no cheap way to tell."""
    if key == "x":
        with db.connect() as con:
            urls = [r[0] for r in con.execute("SELECT url FROM sources")]
        url = next((u for u in urls if sources.kind_of(u) == "x"), None)
        if not url:
            return None                    # nothing to read: no reason to bother X
        try:
            next(iter(sources.site_for(url).pages(url)), None)
            return True
        except sources.LoginRequired:
            return False
        except net.SlowDown:
            return None                    # busy with another listing, or resting: no answer
    site = next((s for s in sources.SITES if s.KIND == key.split(":", 1)[0]), None)
    check = getattr(site, "still_logged_in", None)
    return check(key) if check else None


def _upgrade_gallery_dl():
    """Once a week: X changes its insides about as often, and gallery-dl follows."""
    from .sources import _gdl
    last = db.get_setting("gdl_updated") or ""
    now = datetime.datetime.now(datetime.timezone.utc)
    if config.FROZEN or not _gdl.available() or (last and (now - datetime.datetime.fromisoformat(last)).days < 7):
        return
    db.set_setting("gdl_updated", now.isoformat())
    try:
        _gdl.upgrade()
    except Exception as e:
        log.info("gallery-dl not updated: %s", e)


def _hours_since(stamp):
    try:
        then = datetime.datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return 1e9
    return (datetime.datetime.now(datetime.timezone.utc) - then).total_seconds() / 3600


def check_accounts(keys=None, spread=False, fresh_hours=0):
    """Ask every saved login (or those in keys) whether the site still takes it.
    Returns {label: True (works) / False (ran out) / None (not checked) / reason}.

    spread: a pause of a few seconds between two sites, never all at once.
    fresh_hours: a login checked more recently counts as it was found then,
    without asking -- X, which can only be asked by reading a timeline, a day.
    A site that is resting is not asked at all."""
    found, first = {}, True
    for a in accounts.accounts():
        if not a["logged_in"] or (keys and a["key"] not in keys):
            continue
        name = a["label"] if a["group"] not in ("Mastodon", "Misskey") else "%s (%s)" % (a["group"], a["label"])
        stamp = accounts.saved(a["key"])
        if net.paused(_site_url(a["key"])):
            found[name] = "resting"
            continue
        fresh = max(fresh_hours, 24 if a["key"] == "x" and not keys else 0)
        if fresh and a["state"] == "ok" and _hours_since(a["checked"]) < fresh:
            found[name] = True
            continue
        if spread and not first:
            time.sleep(random.uniform(5, 30))
        first = False
        try:
            ok = _still_logged_in(a["key"])
        except Exception as e:             # no answer says nothing about the login
            log.info("%s: login not checked: %s", a["key"], net.reason(e))
            found[name] = net.reason(e)
            continue
        found[name] = ok
        if ok is True:
            accounts.mark(a["key"], True, stamp=stamp)
        elif ok is False:
            _login_ran_out(a["key"], a["label"], stamp)
    return found


def _site_url(key):
    """A URL of the site a login belongs to, for its pause."""
    if key in accounts.SITES:
        return "https://" + accounts.SITES[key][2][0]
    if key == "bluesky":
        return "https://bsky.app"
    return "https://" + key.split(":", 1)[1]


def _and(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def check_accounts_at_start():
    """Every saved login, once at every start, said in the activity log."""
    try:
        found = check_accounts(spread=True, fresh_hours=CHECKED_HOURS)
    except Exception:
        log.exception("account check")
        return
    works = [n for n, ok in found.items() if ok is True]
    out = [n for n, ok in found.items() if ok is False]
    unsure = ["%s (%s)" % (n, ok) for n, ok in found.items() if isinstance(ok, str) and ok != "resting"]
    if not works and not out and not unsure:
        return
    parts = (["%s work%s" % (_and(works), "s" if len(works) == 1 else "")] if works else []) + \
            (["%s ran out" % _and(out)] if out else []) + \
            (["no answer from %s" % _and(unsure)] if unsure else [])
    event("error" if out else "warn" if unsure else "info", "Logins checked: " + "; ".join(parts))


# ---- profile pictures and names ---------------------------------------------------

def _ordered_sources(con, artist):
    """The card's sources, the master first: its picture and name are the ones meant."""
    return con.execute("SELECT * FROM sources WHERE artist_id = ? ORDER BY (id = ?) DESC, id",
                       (artist["id"], artist["master_source_id"] or 0)).fetchall()


def _note_links(source_id, info):
    """What the profile of a source names (sources.profile_links) -- combining cards uses it."""
    if isinstance(info, dict) and "links" in info:
        with db.connect() as con:
            con.execute("UPDATE sources SET links = ? WHERE id = ?", (json.dumps(info["links"]) if info["links"] else None, source_id))


def _set_avatar(artist_id, url, headers=None):
    """Where the site has the profile picture. Nothing is fetched or kept: the page shows it through /api/avatar,
    which fetches it into memory when somebody looks."""
    if not isinstance(url, str) or not url.startswith("https://"):
        return
    with db.connect() as con:
        con.execute("UPDATE artists SET avatar_url = ?, avatar_headers = ?, avatar_checked = ? WHERE id = ?",
                    (url, json.dumps(headers) if headers else None, _now(), artist_id))


class Busy(Exception):
    """The card is being synced right now."""


def merge(into_id, other_id, auto=False):
    """The card other_id becomes part of into_id: its sources, files and history move over and it
    is gone -- the way to put one artist's accounts together where the sites were not recognised as
    one. The downloaded files stay where they are (paths are kept). The result is a card the user
    acted on, so it is no longer only listed -- unless Sourcerer did it (auto: follows.combine) and
    both were listed, when nobody has touched the result and it stays out of every sweep, and one
    summary, not a line per merge, goes to the activity log. Returns how many sources moved."""
    if into_id == other_id:
        raise ValueError("Pick another card.")
    with _lock:       # looked at and taken off the waiting list in one step: the worker cannot pop it between
        if {into_id, other_id} & (set(_running) | _starting):
            raise Busy("The card is being synced. Try again when it is done.")
        _unqueue(other_id)
    moved = 0
    with db.connect() as con:
        a = con.execute("SELECT * FROM artists WHERE id = ?", (into_id,)).fetchone()
        b = con.execute("SELECT * FROM artists WHERE id = ?", (other_id,)).fetchone()
        if not a or not b:
            raise KeyError(into_id if not a else other_id)
        for src in con.execute("SELECT id, url FROM sources WHERE artist_id = ? ORDER BY id", (other_id,)).fetchall():
            same = con.execute("SELECT id FROM sources WHERE artist_id = ? AND url = ?", (into_id, src["url"])).fetchone()
            if same:                               # the same link on both: the one already there stays
                con.execute("UPDATE files SET source_id = ? WHERE source_id = ?", (same[0], src["id"]))
                con.execute("DELETE FROM sources WHERE id = ?", (src["id"],))
            else:
                con.execute("UPDATE sources SET artist_id = ? WHERE id = ?", (into_id, src["id"]))
                moved += 1
        # A file both cards have under one remote_key stays with the card that has it (a duplicate row
        # of the other card goes with that card); everything else is now into_id's.
        con.execute("UPDATE OR IGNORE files SET artist_id = ? WHERE artist_id = ?", (into_id, other_id))
        # What stayed behind clashed with a record of into_id. Where that record is a duplicate without a
        # file (path NULL) and the other card holds the real one, the file goes to the record -- or it
        # would stay in the folder with no card knowing it, and be downloaded a second time.
        for f in con.execute("SELECT * FROM files WHERE artist_id = ? AND path IS NOT NULL", (other_id,)).fetchall():
            con.execute("UPDATE files SET path = ?, sha256 = ?, phash = ?, width = ?, height = ?, size = ?, "
                        "post_url = COALESCE(post_url, ?), posted = COALESCE(posted, ?) "
                        "WHERE artist_id = ? AND remote_key = ? AND path IS NULL",
                        (f["path"], f["sha256"], f["phash"], f["width"], f["height"], f["size"],
                         f["post_url"], f["posted"], into_id, f["remote_key"]))
        con.execute("UPDATE OR IGNORE failures SET artist_id = ? WHERE artist_id = ?", (into_id, other_id))
        master = a["master_source_id"]
        if not master and b["master_source_id"] and con.execute(
                "SELECT 1 FROM sources WHERE id = ? AND artist_id = ?", (b["master_source_id"], into_id)).fetchone():
            master = b["master_source_id"]
        con.execute("UPDATE artists SET listed = ?, master_source_id = ?, avatar_url = ?, avatar_headers = ?, "
                    "last_activity = ?, favorite = ?, "
                    "pending = (SELECT COALESCE(SUM(pending), 0) FROM sources WHERE artist_id = ?) WHERE id = ?",
                    (1 if auto and a["listed"] and b["listed"] else 0, master,
                     a["avatar_url"] or b["avatar_url"], a["avatar_headers"] if a["avatar_url"] else b["avatar_headers"],
                     max(filter(None, [a["last_activity"], b["last_activity"]]), default=None),
                     1 if a["favorite"] or b["favorite"] else 0, into_id, into_id))      # a star stays on the merged card
        con.execute("DELETE FROM artists WHERE id = ?", (other_id,))
    if not auto:
        event("info", "%s is part of %s now" % (b["name"], a["name"]))
    return moved


def check_card(artist_id):
    """Ask every source who the account is: the dots on the card, and the profile picture."""
    with db.connect() as con:
        artist = con.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        rows = _ordered_sources(con, artist) if artist else []
    found = None
    for row in rows:
        if not sources.site_for(row["url"]):
            continue
        error = level = None
        try:
            info = sources.profile(row["url"]) or {}
            found = found or (info if info.get("avatar") else None)
            _note_links(row["id"], info)
        except Exception as e:
            error, level = net.reason(e), net.level(e)
        with db.connect() as con:
            con.execute("UPDATE sources SET last_checked = datetime('now'), last_error = ?, "
                        "last_level = ? WHERE id = ?", (error, level, row["id"]))
    try:
        if found:
            _set_avatar(artist_id, found["avatar"], found.get("avatar_headers"))
    except Exception as e:
        log.info("no profile picture for card %d: %s", artist_id, e)


def refresh_avatar(artist_id, force=False):
    """The profile picture again, at most every AVATAR_DAYS days -- artists change theirs."""
    with db.connect() as con:
        artist = con.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        rows = _ordered_sources(con, artist) if artist else []
    if not artist:
        return
    if not force and artist["avatar_checked"]:
        age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(
            artist["avatar_checked"]).replace(tzinfo=datetime.timezone.utc)
        if age.days < AVATAR_DAYS:
            return
    for row in rows:
        try:
            info = sources.profile(row["url"])
            _note_links(row["id"], info)
            if info and info.get("avatar"):
                _set_avatar(artist_id, info["avatar"], info.get("avatar_headers"))
                return
        except Exception as e:
            log.info("no profile picture from %s: %s", row["url"], net.reason(e))
    with db.connect() as con:
        con.execute("UPDATE artists SET avatar_checked = ? WHERE id = ?", (_now(), artist_id))


# ---- one artist ---------------------------------------------------------------

def _too_soon(src, site, auto):
    """An automatic sync leaves a site where accounts get locked alone for MIN_HOURS."""
    hours = MIN_HOURS.get(net.site_of(src["url"])) or MIN_HOURS.get(site.KIND)
    if not auto or not hours or not src["last_checked"]:
        return False
    return _hours_since(src["last_checked"].replace(" ", "T") + "+00:00") < hours


def _space_out(where, artist_id, focused=False):
    """A card after a card on the same login site: a pause first, as a person
    moving on to the next artist would take -- not the next request at once."""
    used = _used.get(where)
    if used and used[0] != artist_id:
        wait = random.uniform(*(FOCUS_GAP if focused else next_card())) - (time.monotonic() - used[1])
        if wait > 0:
            (_cancels.get(artist_id) or threading.Event()).wait(wait)


def _gave_up(artist_id, key, failed):
    """Count a file's failed syncs; True once it should no longer hold its source back."""
    with db.connect() as con:
        if not failed:
            con.execute("DELETE FROM failures WHERE artist_id = ? AND remote_key = ?", (artist_id, key))
            return False
        con.execute("INSERT INTO failures (artist_id, remote_key, count) VALUES (?, ?, 1) "
                    "ON CONFLICT (artist_id, remote_key) DO UPDATE SET count = count + 1", (artist_id, key))
        return con.execute("SELECT count FROM failures WHERE artist_id = ? AND remote_key = ?",
                           (artist_id, key)).fetchone()[0] >= GIVE_UP


_P0 = re.compile(r"_p\d+$")


def _held(artist_id, keys):
    """Files not tried this time (a site rested, the sync was cancelled or capped): they
    count as unfinished, so a site that skips what it knows lists their chunk again."""
    with db.connect() as con:
        con.executemany("INSERT OR IGNORE INTO failures (artist_id, remote_key, count) VALUES (?, ?, 0)",
                        [(artist_id, k) for k in keys])


def _sync_artist(artist_id, auto=False, only=None, mode=None):
    with db.connect() as con:
        artist = con.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        if not artist:
            return
        # No mode asked for: a card with auto-download downloads what it finds, any other only looks.
        download = (mode or ("download" if artist["auto_download"] else "refresh")) == "download"
        scanning = mode == "scan"
        rows = con.execute("SELECT * FROM sources WHERE artist_id = ? ORDER BY id",
                           (artist_id,)).fetchall()
        known = {r[0] for r in con.execute(
            "SELECT remote_key FROM files WHERE artist_id = ?", (artist_id,))}
        held = con.execute("SELECT remote_key, count FROM failures WHERE artist_id = ?",
                           (artist_id,)).fetchall()
    # A site that skips what is saved by a work's first page (pixiv) must still list a work
    # whose other pages are unfinished -- and not one given up on, which would be listed on
    # every sync for nothing.
    pending = {r[0] for r in held if r[1] < GIVE_UP}
    skip = (known | {_P0.sub("_p0", r[0]) for r in held if r[1] >= GIVE_UP}) - \
           {_P0.sub("_p0", k) for k in pending}
    master = artist["master_source_id"] if artist["dedupe"] == "master" else None
    # The master first: its copies are then already there when the others come,
    # instead of replacing theirs one by one afterwards.
    srcs = sorted((s for s in rows if sources.site_for(s["url"]) and (not only or s["id"] in only)),
                  key=lambda s: s["id"] != master)
    cur = {"artist_id": artist_id, "name": artist["name"], "phase": "scan", "done": 0, "total": 0,
           "first": any(not s["complete"] for s in srcs), "new": 0, "duplicates": 0,
           "failed": 0, "existing": 0, "file": "", "size": 0, "found": 0,
           "mode": "download" if download else "scan" if scanning else "refresh"}
    with _lock:
        _running[artist_id] = cur
        if len(_running) == 1:
            _speed.clear()
    if not scanning:             # (a scan of hundreds of cards would fill the log with "Checking" and ask every profile again)
        event("start", "Checking %d %s" % (len(srcs), "source" if len(srcs) == 1 else "sources"), artist)
        refresh_avatar(artist_id)

    todo, walked, logins, looked = [], {}, set(), set()
    gave_up = {r[0] for r in held if r[1] >= GIVE_UP}      # a look does not count what was given up on
    with _lock:
        focused = artist_id in _focused                    # Browse opened this card: its sites' pauses are the short ones
        _focused.discard(artist_id)

    def look(src):
        """One source looked at: what it found, or why not. None: left alone (cancelled, or too soon after the last sync)."""
        if _cancelled(cur):
            return None
        site = sources.site_for(src["url"])
        where = net.site_of(src["url"])
        login = sources.account_key(src["url"])
        login = login if login and accounts.logged_in(login) else None
        careful = bool(login) and accounts.careful(login)      # only a cookie login is spaced out: see accounts.careful
        stamp = accounts.saved(login) if login else None
        out = {"fresh": [], "walked": None, "looked": False, "careful": None, "site": site}
        error = level = None
        rest = net.paused(src["url"])
        if rest:                                  # not even one request: the site said stop
            error, level = "%s rests until %s: %s" % (site.LABEL, time.strftime(
                "%H:%M", time.localtime(rest[0])), rest[1]), "warn"
        elif _too_soon(src, site, auto):
            return None
        else:
            if careful:
                _space_out(where, artist_id, focused)
                out["careful"] = where
            try:
                if download:
                    fresh, out["walked"], capped = _scan(src, site, known, cur, skip, bool(pending))
                elif scanning:
                    fresh, capped = _peek(src, site, cur), False
                else:
                    fresh, capped = _glance(src, site, known | gave_up, cur), False
                out.update(looked=True, fresh=fresh)
                if capped and src["complete"]:
                    # The early stop would skip the rest of this backlog: walk on next time.
                    with db.connect() as con:
                        con.execute("UPDATE sources SET complete = 0 WHERE id = ?", (src["id"],))
                # No "still logged in" from a scan that went well: Mastodon and Bluesky
                # read as a visitor when a login died, Patreon answers one as a guest.
            except Exception as e:
                error, level = net.reason(e), net.level(e)
                if login and error.startswith(net.LOGIN_PREFIX):
                    _login_ran_out(login, site.LABEL, stamp)
                elif not isinstance(e, net.SlowDown):    # a pause says so itself, once
                    event("warn", "%s could not be reached: %s" % (site.LABEL, error), artist)
        with db.connect() as con:
            con.execute("UPDATE sources SET last_checked = datetime('now'), last_error = ?, "
                        "last_level = ? WHERE id = ?", (error, level, src["id"]))
        return out

    # The card's sources are looked at side by side where they are on different sites -- each site has its own
    # lane and its own pauses, so one slow site (X through gallery-dl) no longer holds the others up. The ones on one
    # site go one after the other. The results are put together in the order of the sources: the master's first.
    results, by_site = {}, collections.OrderedDict()
    for src in srcs:
        by_site.setdefault(net.site_of(src["url"]), []).append(src)

    def look_site(group):
        for src in group:
            try:
                results[src["id"]] = look(src)
            except Exception:
                log.exception("looking at %s", src["url"])

    if len(by_site) > 1:
        with ThreadPoolExecutor(max_workers=len(by_site)) as pool:
            list(pool.map(look_site, by_site.values()))
    else:
        for group in by_site.values():
            look_site(group)
    for src in srcs:
        out = results.get(src["id"])
        if not out:
            continue
        if out["careful"]:
            logins.add(out["careful"])
        if out["walked"] is not None:
            walked[src["id"]] = out["walked"]
        if out["looked"]:
            looked.add(src["id"])
            todo += [(src, out["site"], m) for m in out["fresh"]]

    if scanning:
        return _peeked(artist, todo, cur, logins, looked)
    if not download:
        return _looked(artist, todo, cur, logins, looked)
    with _lock:
        cur.update(phase="download", total=len(todo))
    failed_sources = set()
    remaining = collections.Counter(src["id"] for src, _site, _m in todo)   # per source: still to download
    unsettled = collections.defaultdict(set)                                  # ... and which
    for src, _site, m in todo:
        unsettled[src["id"]].add(m.remote_key)
    net.configure(per_host=db.setting_int("per_host", 1, 32), pace_ms=db.setting_int("pace_ms", 0, 5000))

    def one(job):
        src, site, media = job
        if _cancelled(cur):
            return
        done = _fetch(artist, src, site, media, cur)
        settled = bool(done)
        if done is None:                           # its site rests: not tried, not counted
            failed_sources.add(src["id"])
        elif _gave_up(artist_id, media.remote_key, not done):
            settled = True                         # nobody waits for it any more
            event("warn", "Gave up on %s after %d failed syncs" % (media.post_url or media.url, GIVE_UP), artist,
                  post=media.post_url or "", key=media.remote_key)
        elif not done:
            failed_sources.add(src["id"])
        with _lock:
            cur["done"] += 1
            if settled:
                remaining[src["id"]] -= 1
                unsettled[src["id"]].discard(media.remote_key)

    with ThreadPoolExecutor(max_workers=db.setting_int("parallel", 1, 64)) as pool:
        list(pool.map(one, todo))
    left = [m.remote_key for _src, site, m in todo if getattr(site, "SKIPS_KNOWN", False)]
    if left:
        with db.connect() as con:
            have = {r[0] for r in con.execute("SELECT remote_key FROM files WHERE artist_id = ?", (artist_id,))}
        _held(artist_id, [k for k in left if k not in have])
    for where in logins:
        _used[where] = (artist_id, time.monotonic())

    cancelled = _cancelled(cur)
    with db.connect() as con:
        # Complete only after a sync went all the way and got everything: until
        # then the next one walks the whole history again and finds what is missing.
        for sid, ok in walked.items():
            if ok and not cancelled and sid not in failed_sources:
                con.execute("UPDATE sources SET complete = 1, walked = ? WHERE id = ?", (_now(), sid))
        con.execute("UPDATE artists SET last_sync = ?, last_new = ?, last_failed = ?, "
                    "last_activity = CASE WHEN ? THEN ? ELSE last_activity END WHERE id = ?",
                    (_now(), cur["new"], cur["failed"], cur["new"] > 0, _now(), artist_id))
        # What is left to download of each source that was read: what failed or was cut off. A source
        # that was not read (resting, an error, skipped, or outside this ask) keeps its count.
        _set_pending(con, artist_id, {sid: max(0, remaining[sid]) for sid in looked}, unsettled)
    event("cancelled" if cancelled else ("done" if not cur["failed"] else "warn"),
           "Cancelled" if cancelled else "Finished", artist,
           new=cur["new"], duplicates=cur["duplicates"], failed=cur["failed"], existing=cur["existing"])


def _peek(src, site, cur):
    """A scan: the newest page of a source, kept as its snapshot (Browse opens from it and "Latest activity" reads the
    newest post's date from it), and which of its posts the last look did not have -- not which the library lacks. One
    request. With no earlier snapshot there is nothing to compare: nothing is claimed new."""
    before = snapshots.load(src["id"])
    old = {m.remote_key for m in before.items} if before else None
    listing = site.pages(src["url"])
    try:
        items = next(listing, [])
    finally:
        close = getattr(listing, "close", None)
        if close:
            close()
    snapshots.save(src["id"], items)
    fresh = [m for m in items if old is not None and m.remote_key not in old]
    with _lock:
        cur["found"] += len(fresh)
    return fresh


def _peeked(artist, todo, cur, logins, looked):
    """The end of a scan: said only when something is new (a sweep over hundreds of cards must not bury the log), and
    when nothing could be asked. Nothing is counted against the library."""
    artist_id = artist["id"]
    for where in logins:
        _used[where] = (artist_id, time.monotonic())
    cancelled = _cancelled(cur)
    with db.connect() as con:
        con.execute("UPDATE artists SET last_sync = ? WHERE id = ?", (_now(), artist_id))
    if cancelled:
        event("cancelled", "Cancelled", artist)
    elif not looked:
        event("info", "Nothing could be checked", artist)
    elif todo:
        event("info", "%d new post%s online since the last look" % (len(todo), "" if len(todo) == 1 else "s"), artist,
              new=len(todo))


def _glance(src, site, known, cur):
    """The newest posts of a source -- REFRESH_ITEMS of them, or REFRESH_PAGES pages -- and which
    of them are not downloaded. Kept as the source's snapshot. No walk through the history, no
    skip list, nothing marked complete: this only looks."""
    fresh, seen, items = [], set(), []
    listing = site.pages(src["url"])
    try:
        for number, page in enumerate(listing, 1):
            items += page
            new = [m for m in page if m.remote_key not in known and m.remote_key not in seen]
            seen.update(m.remote_key for m in new)
            fresh += new
            with _lock:
                cur["found"] += len(new)
            # Newest first: when the page's oldest post is in the library, everything older is there as well -- no need
            # for the next pages (a refresh once read four pages of every artist to say "up to date"). The oldest, not
            # any: somebody who saved one new picture by hand has the rest of the page still to download.
            if (page and page[-1].remote_key in known) or len(items) >= REFRESH_ITEMS or number >= REFRESH_PAGES \
                    or _cancelled(cur):
                break
    finally:
        close = getattr(listing, "close", None)
        if close:
            close()
    snapshots.save(src["id"], items)
    return fresh


def _set_pending(con, artist_id, counts, keys=None):
    """counts: source id -> how many of its newest posts are not in the library; keys: source id -> which
    (the first PENDING_KEYS). The card's number is the sum over its sources, so one that was not read
    this time keeps what it had."""
    keys = keys or {}
    con.executemany("UPDATE sources SET pending = ?, pending_keys = ? WHERE id = ?",
                    [(n, json.dumps(sorted(keys.get(sid, ()))[:PENDING_KEYS]), sid) for sid, n in counts.items()])
    con.execute("UPDATE artists SET pending = (SELECT COALESCE(SUM(pending), 0) FROM sources WHERE artist_id = ?) "
                "WHERE id = ?", (artist_id, artist_id))


def _looked(artist, todo, cur, logins, looked):
    """The end of a sync that only looked: how many posts wait for a download, shown on the card;
    A card with auto-download never comes here. A look only
    reads the newest REFRESH_ITEMS posts of a source: a count above that is "at least"."""
    artist_id = artist["id"]
    found = collections.Counter(src["id"] for src, _site, _m in todo)
    for where in logins:
        _used[where] = (artist_id, time.monotonic())
    cancelled = _cancelled(cur)
    with db.connect() as con:
        con.execute("UPDATE artists SET last_sync = ? WHERE id = ?", (_now(), artist_id))
        if not cancelled:
            waits = collections.defaultdict(set)
            for src, _site, m in todo:
                waits[src["id"]].add(m.remote_key)
            _set_pending(con, artist_id, {sid: found[sid] for sid in looked}, waits)
        waiting = con.execute("SELECT pending FROM artists WHERE id = ?", (artist_id,)).fetchone()[0]
    if cancelled:
        event("cancelled", "Cancelled", artist)
    elif not looked:                               # every source rests, failed or was left alone for now
        event("info", "Nothing could be checked", artist)
    else:
        event("done", "%d%s new post%s to download" % (waiting, "+" if waiting >= REFRESH_ITEMS else "", "" if waiting == 1 else "s")
              if waiting else "Up to date", artist)


def pending_down(artist_id, source_id, key):
    """A post of this source was saved from Browse: if the last look counted it as waiting, one fewer does."""
    with db.connect() as con:
        row = con.execute("SELECT pending_keys FROM sources WHERE id = ?", (source_id,)).fetchone()
        try:
            keys = json.loads(row[0] or "[]") if row else []
        except ValueError:
            keys = []
        if key not in keys:
            return
        keys.remove(key)
        con.execute("UPDATE sources SET pending = MAX(pending - 1, 0), pending_keys = ? WHERE id = ?",
                    (json.dumps(keys), source_id))
        _set_pending(con, artist_id, {})


def _walk_again(src, site):
    """A site whose old posts can join a source later -- a booru post tagged
    with the artist years after it was uploaded -- is walked all the way now
    and then (the site's FULL_WALK_DAYS)."""
    days = getattr(site, "FULL_WALK_DAYS", 0)
    if not days:
        return False
    try:
        last = datetime.datetime.fromisoformat(src["walked"] or "").replace(tzinfo=datetime.timezone.utc)
    except ValueError:                     # never walked since the column came
        return True
    return (datetime.datetime.now(datetime.timezone.utc) - last).days >= days


def _scan(src, site, known, cur, skip=frozenset(), retry=False):
    """What this source has that is new: (media newest first, walked-to-the-end
    flag, stopped-at-a-cap flag). skip: what a site that can skip what is known
    without asking for it (pixiv's chunks) may leave out; retry: some file is
    unfinished, so such a site walks on instead of stopping at the first known page."""
    fresh, seen = [], set()
    skips = getattr(site, "SKIPS_KNOWN", False)
    listing = site.pages(src["url"], skip) if skips else site.pages(src["url"])
    for number, page in enumerate(listing, 1):
        if number == 1 and not skips:        # (a site that skips what is saved lists only part of its first page)
            snapshots.save(src["id"], page)
        new = [m for m in page if m.remote_key not in known and m.remote_key not in seen]
        seen.update(m.remote_key for m in new)
        fresh += new
        with _lock:
            cur["found"] += len(new)
        # A site that limits how much one sync may take (pixiv's terms): the
        # rest comes with the next sync, which walks on from where this stopped.
        cap = getattr(site, "MAX_NEW", 0)
        if cap and len(fresh) >= cap:
            event("info", "%s: %d new files this time; the next sync fetches more." % (site.LABEL, cap))
            if skips:                      # a work cut in two must be listed again
                _held(src["artist_id"], [m.remote_key for m in fresh[cap:]])
            return fresh[:cap], False, True
        # Newest first: once a page holds something already seen, everything
        # older was seen too -- but only after one sync has gone all the way.
        if src["complete"] and len(new) < len(page) and not (skips and retry) and not _walk_again(src, site):
            return fresh, True, False
        if number >= MAX_PAGES:
            event("info", "%s: stopped after %d pages; the next sync carries on." % (
                site.LABEL, number))
            return fresh, False, True
        if _cancelled(cur):
            return fresh, False, False
    return fresh, True, False


def _fetch(artist, src, site, media, cur):
    """Download one file: True when it is there (or a duplicate), False when it
    failed, None when its site rests and it was not even asked for."""
    folder = target_folder(artist, site.LABEL)
    if _adopt(artist, src, media, folder, cur):
        return True
    try:
        if media.fetch:
            part, sha, ext, server_name = media.fetch(folder, _count_bytes)
        else:
            part, sha, ext, server_name = net.download(media.url, folder, media.mime, _count_bytes,
                                                       headers=media.headers)
    except net.SlowDown:                           # the site rests: said once, when it began
        with _lock:
            cur["failed"] += 1
        return None
    except Exception as e:
        reason = net.reason(e)
        login = sources.account_key(src["url"])
        if login and reason.startswith(net.LOGIN_PREFIX) and accounts.logged_in(login):
            _login_ran_out(login, site.LABEL)     # pixiv's /pages answers a dead login with 401
        else:
            # post and key: the activity log jumps to the picture in the artist's gallery, or to its post
            event("warn", "Download failed: %s (%s)" % (media.post_url or media.url, reason), artist,
                  post=media.post_url or "", key=media.remote_key)
        with _lock:
            cur["failed"] += 1
        return False
    size = part.stat().st_size
    phash, width, height = imaging.info(part)
    with _save:
        path = _final_path(folder, media, ext, server_name, media.posted)
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
            _record(con, artist, src, media, sha, str(path) if keep else None, phash, width, height, size)
    return True


def _record(con, artist, src, media, sha, path, phash, width, height, size):
    """The file's row. One that exists keeps its place -- unless its file is gone (the user deleted it and downloaded it again,
    maybe under another name): then it points at the new one, or the picture would stay "not downloaded"."""
    old = con.execute("SELECT id, path FROM files WHERE artist_id = ? AND remote_key = ?",
                      (artist["id"], media.remote_key)).fetchone()
    if old is None:
        con.execute("INSERT INTO files (artist_id, source_id, remote_key, sha256, path, post_url, posted, phash, "
                    "width, height, size) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (artist["id"], src["id"], media.remote_key, sha, path, media.post_url, media.posted,
                     phash, width, height, size))
    elif path and not (old["path"] and os.path.isfile(old["path"])):
        con.execute("UPDATE files SET source_id = ?, sha256 = ?, path = ?, phash = ?, width = ?, height = ?, size = ? "
                    "WHERE id = ?", (src["id"], sha, path, phash, width, height, size, old["id"]))


def _local_names(media):
    """Glob patterns a copy of this file already in the folder would match: its
    own name, also with the date in front (Settings > File names)."""
    if media.local:
        stems = media.local
    elif media.filename:
        stem = os.path.splitext(safe_name(media.filename))[0]
        # A name every other upload has ("image.png" on Patreon) says nothing
        # about which picture it is: such a file is downloaded, not guessed at.
        if len(stem) < 8 or re.match(r"(?i)(image|untitled|file|photo|picture|unknown|download)\b", stem):
            return []
        stems = [glob.escape(stem) + ".*"]
    else:
        return []
    return stems + ["????-??-??_" + s for s in stems]


def _adopt(artist, src, media, folder, cur):
    """A file that is already there is taken over, not downloaded again: from
    the archive of a deleted card, or under its own name in the card's folder
    (a card made again, a collection that was there before Sourcerer)."""
    with _save, db.connect() as con:
        known = con.execute("SELECT * FROM archive WHERE remote_key = ?", (media.remote_key,)).fetchone()
        if known and known["path"] and os.path.isfile(known["path"]):
            path, sha, phash = known["path"], known["sha256"], known["phash"]
            width, height, size = known["width"], known["height"], known["size"]
        else:
            path = None
            for pattern in _local_names(media) if folder.is_dir() else []:
                for candidate in folder.glob(pattern):
                    taken = con.execute("SELECT 1 FROM files WHERE path = ?", (str(candidate),)).fetchone()
                    if candidate.is_file() and not taken:
                        path = str(candidate)
                        break
                if path:
                    break
            if not path:
                return False
            sha, size = _sha256(path), os.path.getsize(path)
            phash, width, height = imaging.info(path)
        _record(con, artist, src, media, sha, path, phash, width, height, size)
        con.execute("DELETE FROM archive WHERE remote_key = ?", (media.remote_key,))
    with _lock:
        cur["existing"] += 1
    return True


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
