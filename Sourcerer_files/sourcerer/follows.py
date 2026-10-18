"""The accounts a login follows, as artists in the list.

Logging in tells a site who you are, and the site knows whom you follow: Bluesky, Mastodon and
pixiv list that (`following(key)` in their modules, yielding (list name, pages of {"url", "name",
"avatar"})). Every followed account becomes a card -- once -- so the list fills itself and a source
needs no pasted link. Such a card is only *listed* (`artists.listed`): nothing reads its sites in
the background and nothing downloads until the user does something with it, because hundreds of
cards looked at by every sweep (Sync all, previews, All artists) would be hundreds of requests
nobody asked for.

What is added is remembered (`followed`, by lower-cased profile URL), so a card the user deleted
does not come back and a card merged into another is not made again. A list read to its end once
by this login is read again only up to its first page of known accounts: the newest follows come
first, and the rest would be the same requests again for nothing.

The lists are the sites' words, not ours: a link is taken only when it is a profile of the list's
own site (never another site's address, which could cost a request on a login), and a picture only
from a public https address.
"""
import json
import logging
import random
import threading
import time
import urllib.parse

from . import accounts, db, net, sources, sync

log = logging.getLogger(__name__)
HOURS = (10, 14)             # between two looks at the lists, while Sourcerer runs
TRIES = 2                    # a picture that fails this often is let be
version = 0                  # counts the changes the page should reload for (cards made, pictures saved)
_bumped = 0.0
_lock = threading.Lock()     # one look at a time
_pic_lock = threading.Lock()
_picturer = None


def _touch(force=False):
    """The page reloads its list when this moves: at most every few seconds while a long list is read."""
    global version, _bumped
    if force or time.monotonic() - _bumped > 4:
        _bumped = time.monotonic()
        version += 1


def _site(key):
    return next((s for s in sources.SITES if s.KIND == key.split(":", 1)[0]), None)


def keys():
    """The saved logins that still work and whose site lists follows."""
    return [a["key"] for a in accounts.accounts()
            if a["logged_in"] and a["state"] != "expired" and getattr(_site(a["key"]), "following", None)]


def _name(f, url):
    name = " ".join((f.get("name") or "").split())[:200]
    return name or urllib.parse.unquote(urllib.parse.urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])


def _who(url):
    """What tells two accounts of one name apart: their handle."""
    parts = urllib.parse.urlsplit(url)
    last = urllib.parse.unquote(parts.path.rstrip("/").rsplit("/", 1)[-1]).lstrip("@")
    if parts.hostname in ("bsky.app", "bsky.social"):
        return last
    if parts.hostname and parts.hostname.endswith("pixiv.net"):
        return "pixiv " + last
    return last if "@" in last else "%s@%s" % (last, parts.hostname)


def _unique(name, url, taken):
    """A card's folder is its name: two accounts called Mochi must not share one."""
    cand, n = name, 1
    while sync.safe_name(cand).lower() in taken:
        n += 1
        cand = "%s (%s)" % (name, _who(url)) + (" %d" % n if n > 2 else "")
    taken.add(sync.safe_name(cand).lower())
    return cand


def _add(page, kind, public):
    """Cards for the accounts of a page not seen before. Returns (cards made, page was all known).
    public: host -> whether it is a public one, kept for the whole look."""
    mine = []
    for f in page:
        raw = f.get("url") or ""
        site = sources.site_for(raw)
        # Only a profile of the list's own site: normalising another site's address (a pixiv work's)
        # is a request, and a hostile server could name any host.
        if site and site.KIND == kind:
            host = urllib.parse.urlsplit(raw).hostname or ""
            if host not in public:
                public[host] = net.public_https(raw)
            if public[host]:
                mine.append((sources.normalize(raw), f))
    made, known = [], len(page) - len(mine)
    with db.connect() as con:
        have = {r[0].lower() for r in con.execute("SELECT url FROM sources")}
        taken = {sync.safe_name(r[0]).lower() for r in con.execute("SELECT name FROM artists")}
        for url, f in mine:
            key = url.lower()
            headers = f.get("avatar_headers")
            if not con.execute("INSERT OR IGNORE INTO followed (url, avatar, headers) VALUES (?, ?, ?)",
                               (key, f.get("avatar") or "", json.dumps(headers) if headers else "")).rowcount:
                known += 1
                continue
            if key in have:
                continue                                    # a card of the user's has it already
            have.add(key)
            artist_id = con.execute("INSERT INTO artists (name, listed) VALUES (?, 1)",
                                    (_unique(_name(f, url), url, taken),)).lastrowid
            con.execute("INSERT INTO sources (artist_id, url, kind) VALUES (?, ?, ?)",
                        (artist_id, url, sources.kind_of(url)))
            made.append(artist_id)
    if made:
        _touch()
        _start_pictures()
    return len(made), bool(page) and known == len(page)


# ---- profile pictures ---------------------------------------------------------------

def _pending_picture():
    with db.connect() as con:
        return con.execute(
            "SELECT f.url, f.avatar, f.headers, s.artist_id FROM followed f JOIN sources s ON lower(s.url) = f.url "
            "JOIN artists a ON a.id = s.artist_id WHERE f.avatar != '' AND f.tried < ? AND a.avatar IS NULL "
            "ORDER BY f.rowid DESC LIMIT 1", (TRIES,)).fetchone()


def _pictures():
    """The profile pictures the lists named, one at a time and unhurried -- they come from a CDN, but
    there can be thousands. Found in the table, so a restart carries on and a failure is tried again
    once; a site that rests ends the run (the next look starts it again)."""
    global _picturer
    saved, public = 0, {}
    while True:
        row = _pending_picture()
        if row is None:
            with _pic_lock:
                row = _pending_picture()
                if row is None:
                    _picturer = None
                    break
        try:
            host = urllib.parse.urlsplit(row["avatar"]).hostname or ""
            if host not in public:
                public[host] = net.public_https(row["avatar"])
            if not public[host]:
                raise ValueError("not a public https address")
            sync._save_avatar(row["artist_id"], row["avatar"], json.loads(row["headers"]) if row["headers"] else None)
            saved += 1
            if saved % 20 == 0:
                _touch()
        except net.SlowDown:
            with _pic_lock:
                _picturer = None
            break
        except Exception as e:
            log.info("no profile picture for card %d: %s", row["artist_id"], net.reason(e))
            with db.connect() as con:
                con.execute("UPDATE followed SET tried = tried + 1 WHERE url = ?", (row["url"],))
        time.sleep(random.uniform(0.2, 0.6))
    if saved:
        _touch(True)


def _start_pictures():
    global _picturer
    with _pic_lock:
        if _picturer is None:
            _picturer = threading.Thread(target=_pictures, daemon=True, name="follow-pictures")
            _picturer.start()


# ---- the lists ------------------------------------------------------------------------

def _look(key):
    """One login's lists. Returns how many cards they made."""
    site, label, total, public = _site(key), accounts.label(key), 0, {}
    # A list read to its end by *this* login (a new login is another account, maybe) may stop early.
    stamp = accounts.saved(key) or "-"
    try:
        for name, pages in site.following(key):
            done = "follows_read:%s:%s" % (key, name)
            for page in pages:
                made, all_known = _add(page, site.KIND, public)
                total += made
                if all_known and db.get_setting(done, "") == stamp:
                    break                    # read to its end before: the rest is known
            else:
                db.set_setting(done, stamp)
    except Exception as e:
        why = net.reason(e)
        log.info("%s: the list of followed accounts stopped: %s", key, why)
        sync.event("warn", "%s: the list of followed accounts stopped (%s); the next look carries on" % (label, why))
    if total:
        _touch(True)
        sync.event("info", "%s: %d followed account%s added to the list" % (label, total, "" if total == 1 else "s"))
    return total


def look(only=None):
    """Every login's followed accounts (or those of the keys in only), one login after another."""
    if db.get_setting("import_follows") != "1":
        return
    with _lock:
        for key in only or keys():
            if net.paused(sync._site_url(key)):
                continue
            _look(key)
    _start_pictures()                        # pictures a rest or a restart left behind


def look_async(only=None):
    threading.Thread(target=look, args=(only,), daemon=True, name="follows").start()


def _after_login(key, how):
    if how in ("new", "renewed") and getattr(_site(key), "following", None):
        look_async([key])


accounts.CHANGED.append(_after_login)


def start():
    """After the start's account check (sync.scheduler) -- an expired login is then known and
    skipped -- and every ten to fourteen hours."""
    def run():
        time.sleep(random.uniform(90, 150))
        while True:
            try:
                look()
            except Exception:
                log.exception("follows")
            time.sleep(random.uniform(*HOURS) * 3600)
    threading.Thread(target=run, daemon=True, name="follows").start()
