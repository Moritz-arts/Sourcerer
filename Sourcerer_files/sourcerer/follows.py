"""The accounts a login follows, as artists in the list.

Logging in tells a site who you are, and the site knows whom you follow: Bluesky, Mastodon and
pixiv list that (`following(key)` in their modules, pages of {"url", "name", "avatar"}). Every
followed account becomes a card -- once -- so the list fills itself and a source needs no pasted
link. Such a card is only *listed* (`artists.listed`): nothing reads its sites in the background
and nothing downloads until the user does something with it, because hundreds of cards looked
at by every sweep (Sync all, previews, All artists) would be hundreds of requests nobody asked for.

What is added is remembered (`followed`, by profile URL), so a card the user deleted does not
come back and a card merged into another is not made again. A look at a list that was read to the
end once stops at its first page of known accounts: the newest follows come first, and the rest
would be the same requests again for nothing.
"""
import logging
import queue
import random
import re
import threading
import time
import urllib.parse

from . import accounts, db, net, sources, sync

log = logging.getLogger(__name__)
HOURS = (10, 14)             # between two looks at the lists, while Sourcerer runs
version = 0                  # counts the cards made, so the page reloads its list
_lock = threading.Lock()     # one look at a time
_avatars = queue.Queue()
_pic_lock = threading.Lock()
_picturer = None


def _site(key):
    return next((s for s in sources.SITES if s.KIND == key.split(":", 1)[0]), None)


def keys():
    """The saved logins that still work and whose site lists follows."""
    return [a["key"] for a in accounts.accounts()
            if a["logged_in"] and a["state"] != "expired" and getattr(_site(a["key"]), "following", None)]


def _name(f, url):
    name = re.sub(r"\s+", " ", re.sub(r":[\w+-]+:", "", f.get("name") or "")).strip()[:200]
    return name or urllib.parse.unquote(urllib.parse.urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])


def _add(page):
    """Cards for the accounts of a page not seen before. Returns (cards made, page was all known)."""
    global version
    made, known = [], 0
    with db.connect() as con:
        for f in page:
            url = sources.normalize(f.get("url") or "")
            if not url or not sources.site_for(url):
                known += 1
                continue
            if not con.execute("INSERT OR IGNORE INTO followed (url) VALUES (?)", (url,)).rowcount:
                known += 1
                continue
            if con.execute("SELECT 1 FROM sources WHERE url = ?", (url,)).fetchone():
                continue                                    # a card of the user's has it already
            artist_id = con.execute("INSERT INTO artists (name, listed) VALUES (?, 1)",
                                    (_name(f, url),)).lastrowid
            con.execute("INSERT INTO sources (artist_id, url, kind) VALUES (?, ?, ?)",
                        (artist_id, url, sources.kind_of(url)))
            made.append((artist_id, f))
    if made:
        version += 1
        for artist_id, f in made:
            if f.get("avatar"):
                _avatars.put((artist_id, f["avatar"], f.get("avatar_headers")))
        _start_pictures()
    return len(made), bool(page) and known == len(page)


def _pictures():
    """The profile pictures the lists named, one at a time and unhurried: they come from a CDN,
    but there can be hundreds."""
    global _picturer
    while True:
        try:
            artist_id, url, headers = _avatars.get(timeout=30)
        except queue.Empty:
            with _pic_lock:
                if _avatars.empty():
                    _picturer = None
                    return
            continue
        try:
            sync._save_avatar(artist_id, url, headers)
        except Exception as e:
            log.info("no profile picture for card %d: %s", artist_id, net.reason(e))
        time.sleep(random.uniform(0.2, 0.6))


def _start_pictures():
    global _picturer
    with _pic_lock:
        if _picturer is None:
            _picturer = threading.Thread(target=_pictures, daemon=True, name="follow-pictures")
            _picturer.start()


def _look(key):
    """One login's lists. Returns how many cards they made."""
    site, label, total = _site(key), accounts.label(key), 0
    try:
        for name, pages in site.following(key):
            done = "follows_read:%s:%s" % (key, name)
            for page in pages:
                made, all_known = _add(page)
                total += made
                if all_known and db.get_setting(done, ""):
                    break                    # read to its end before: the rest is known
            else:
                db.set_setting(done, "1")
    except Exception as e:
        why = net.reason(e)
        log.info("%s: the list of followed accounts stopped: %s", key, why)
        sync.event("warn", "%s: the list of followed accounts stopped (%s); the next look carries on" % (label, why))
    if total:
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
