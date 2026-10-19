"""HTTP: JSON requests and streamed downloads, polite to every site.

Speed comes from reusing connections (one requests.Session per thread, so a
new file costs no new TLS handshake; the gallery's pictures, each asked for on a thread of
its own, share one session, _picture_session) and from downloading several files at
once. Politeness comes from two limits per site: how many requests run at
once, and a pause between two of them -- Settings' values, or a site's own
stricter ones (HOSTS). A 429 or 5xx is waited out, honouring Retry-After,
except on the hosts in STOP_HOSTS: there the source stops and the next sync
carries on. Sourcerer says who it is in its User-Agent and never pretends to
be a browser on the public APIs it uses.

Connections are TLS 1.3 only, on Python's own defaults (_Tls13): bot checks
(baraag.net's, the big forum networks') refuse the handshake urllib3 makes --
the one every Python scraper makes -- whatever the headers say. A server
without TLS 1.3 is remembered and gets the usual handshake (_OLD_TLS).

What keeps a logged-in account safe (an account can be locked, not just a
page refused):
  - a request that carries a login goes alone, at least LOGIN_PACE apart,
    whatever Settings say, and every gap is drawn at random (JITTER) with a
    longer reading break now and then -- a metronome is the easiest robot to spot;
  - a site that says stop -- a 429, a bot check, a lock -- is paused as a whole
    (pause(): every host of the company, all cards, the gallery, the checks),
    for as long as it asks or for hours, and the pause outlives a restart;
  - a day's budget per site (BUDGETS): what is left waits for tomorrow.
"""
import contextlib
import datetime
import email.utils
import hashlib
import http.cookiejar
import ipaddress
import json
import logging
import mimetypes
import os
import random
import re
import socket
import ssl
import threading
import time
import urllib.parse

import requests
from requests.adapters import HTTPAdapter

from . import accounts, config

log = logging.getLogger(__name__)
TIMEOUT = (15, 60)          # connect, read
RETRIES = 4

_local = threading.local()
_lock = threading.Lock()
_hosts = {}                 # (host, carries a login, small pictures) -> its limiter's state
_limits = {"per_host": 4, "pace": 0.25}
CAP = 300                   # the longest Retry-After waited out; a longer one pauses the site

# Sites stricter than Settings: (requests at once, seconds apart). With
# Settings, the gentler of the two wins.
HOSTS = {"www.pixiv.net": (1, 1.5), "i.pximg.net": (2, 0.4), "www.patreon.com": (1, 1.5),
         # A leading dot: every host below that domain (Patreon's and X's file servers).
         ".patreonusercontent.com": (2, 0.6), ".twimg.com": (2, 0.4),
         # The boorus' APIs: e621 asks for at most one request a second, the others
         # are run by volunteers on donated servers.
         "danbooru.donmai.us": (1, 1.0), "safebooru.donmai.us": (1, 1.0), "e621.net": (1, 1.0),
         "gelbooru.com": (1, 1.0), "api.rule34.xxx": (1, 1.0),
         "safebooru.org": (1, 1.0), "yande.re": (1, 1.0), "konachan.com": (1, 1.0),
         "konachan.net": (1, 1.0), "www.sakugabooru.com": (1, 1.0), "aibooru.online": (1, 1.0),
         "xbooru.com": (1, 1.0), "tbib.org": (1, 1.0), "hypnohub.net": (1, 1.0),
         "misskey.io": (2, 0.5),
         # Fanbox and Fantia read with a login: one request at a time, the login lane spaces them further.
         "downloads.fanbox.cc": (2, 0.6), "api.fanbox.cc": (1, 1.5), "fantia.jp": (1, 1.5), "c.fantia.jp": (2, 0.6)}
# Not retried on a 429 or a bot check. pixiv's terms forbid "large numbers of
# actions within a short period"; tools that kept retrying there had accounts restricted.
STOP_HOSTS = {"www.pixiv.net"}

# The gallery's small pictures, from a host that carries no login: a browser opens six
# connections to a CDN to show a page of them, so four at a time, 0.08 s apart, is less
# than that -- and a grid of sixty no longer waits one picture per HOSTS' pace (0.5 s on
# pixiv's image host: half a minute for a page). Originals and anything with a login keep
# the lanes above.
PREVIEW = (4, 0.08)

LOGIN_PACE = 2.0            # seconds at least between two requests carrying a login
TOKEN_PACE = 1.0            # ... carrying only a token (Mastodon allows 300 requests in 5 minutes): no jitter-long gaps, no breaks
INTERACTIVE_PACE = 0.5      # ... when somebody waits for the answer (interactive()): a click, not a scan
JITTER = (1.0, 1.6)         # every gap times this, drawn anew: longer, never shorter
READ_EVERY = (20, 40)       # a logged-in site gets a break after this many requests ...
READ_BREAK = (15, 60)       # ... of this many seconds
# Requests a day carrying a login, per site. pixiv's terms name no number;
# Pikura's users saw 24-72 h suspensions after long batch runs.
BUDGETS = {"pixiv": 1500, "patreon": 1500, "x": 1500, "fanbox": 1500, "fantia": 1500}
BUDGET = 3000

# A site is every host one company runs: a stop from pixiv's API stops its
# image host too, and a day's budget counts them together.
_SITES = {"pixiv.net": "pixiv", "pximg.net": "pixiv", "patreon.com": "patreon",
          "patreonusercontent.com": "patreon", "x.com": "x", "twitter.com": "x", "twimg.com": "x",
          "bsky.app": "bluesky", "bsky.network": "bluesky", "bsky.social": "bluesky",
          "misskey.io": "misskey", "misskeyusercontent.jp": "misskey", "fanbox.cc": "fanbox", "fantia.jp": "fantia"}
NAMES = {"pixiv": "Pixiv", "patreon": "Patreon", "x": "X", "bluesky": "Bluesky", "misskey": "Misskey.io",
         "fanbox": "Fanbox", "fantia": "Fantia"}
PAUSED = []                 # callbacks(site, until, why), for the activity log


class SlowDown(Exception):
    """A site asked Sourcerer to stop for now -- a 429, a bot check, a lock,
    the day's budget -- and is paused (pause())."""


def site_of(url):
    host = (urllib.parse.urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    for suffix, name in _SITES.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    return host


def name_of(site):
    return NAMES.get(site, site)


# ---- pauses and budgets: kept in the database, so a restart does not undo them -------

_state = {}


def _stored(key):
    if key not in _state:
        from . import db
        try:
            _state[key] = json.loads(db.get_setting(key) or "{}")
        except (ValueError, TypeError):
            _state[key] = {}
    return _state[key]


def _store(key):
    from . import db
    db.set_setting(key, json.dumps(_state[key]))


def pause(url, seconds, why):
    """Leave a site alone for seconds: no sync, check or gallery asks it meanwhile."""
    site, until = site_of(url), time.time() + seconds
    with _lock:
        pauses = _stored("paused")
        if pauses.get(site, [0])[0] >= until:
            return
        pauses[site] = [until, why]
        _store("paused")
    log.info("%s paused for %d min: %s", site, seconds // 60, why)
    for fn in PAUSED:
        try:
            fn(site, until, why)
        except Exception:
            log.exception("after pausing %s", site)


# What a pause says when a login began it: a new login ends it (lift).
LOGIN_PAUSES = ("refused the login", "bot check", "took Sourcerer for a bot", "let only a browser through")


def lift(url):
    """A login saved anew ends the rest its refusal or a bot check began -- the advice
    was to log in -- and forgets the refusals counted against the old one."""
    site = site_of(url)
    with _lock:
        _refused.pop(site, None)
        pauses = _stored("paused")
        entry = pauses.get(site)
        if entry and any(w in entry[1] for w in LOGIN_PAUSES):
            del pauses[site]
            _store("paused")


def paused(url):
    """(until, why) while a site is paused, else None."""
    entry = _stored("paused").get(site_of(url))
    return entry if entry and entry[0] > time.time() else None


def pauses():
    """The pauses now running, for the window: [{site, name, until (Unix time), why}]."""
    now = time.time()
    return [{"site": s, "name": name_of(s), "until": e[0], "why": e[1]}
            for s, e in sorted(_stored("paused").items()) if e[0] > now]


def _stopped(url):
    entry = paused(url)
    if entry:
        raise SlowDown("%s rests until %s: %s" % (name_of(site_of(url)),
                                                  time.strftime("%H:%M", time.localtime(entry[0])), entry[1]))


def _hours(low, high):
    return random.uniform(low, high) * 3600


def spend(url, n=1):
    """Count requests that carried a login; past the day's budget the site rests until tomorrow."""
    site, day = site_of(url), time.strftime("%Y-%m-%d")
    with _lock:
        spent = _stored("spent")
        entry = spent.get(site)
        if not entry or entry[0] != day:
            entry = spent[site] = [day, 0]
        entry[1] += n
        over = entry[1] >= BUDGETS.get(site, BUDGET)
        if over or entry[1] % 10 < n:
            _store("spent")
    if over:
        tomorrow = time.mktime(time.strptime(day, "%Y-%m-%d")) + 86400
        pause(url, tomorrow - time.time() + _hours(0.5, 3),
              "today's %d requests are done; the rest follows tomorrow" % BUDGETS.get(site, BUDGET))


_refused = {}               # site -> [refusals in a row, since]


def _refusal(url, ok):
    """A login refused again and again (401/403) is not asked further for a while."""
    site = site_of(url)
    with _lock:
        if ok:
            _refused.pop(site, None)
            return
        count, since = _refused.get(site, [0, time.time()])
        if time.time() - since > 900:
            count, since = 0, time.time()
        _refused[site] = [count + 1, since]
        tripped = count + 1 >= 3
    if tripped:
        pause(url, _hours(2, 4), "it refused the login three times in a row")


def _carries_login(url, headers=None, params=None):
    """True for a request that carries a cookie login or a booru's key (the careful lane: one at a time, LOGIN_PACE apart,
    reading breaks, a daily budget -- what an account gets banned for); "token" for one that only carries a
    token (Mastodon, Bluesky): TOKEN_PACE apart, nothing more; False for none."""
    if accounts.headers_for(url) or (params and any(k in params for k in ("api_key", "login"))):
        return True
    return "token" if any(k.lower() == "authorization" for k in (headers or {})) else False

# Extensions for the content types sites actually send, so a file whose URL
# has none (Mastodon's ".../original", Bluesky's getBlob) still opens properly.
_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
        "image/webp": ".webp", "image/avif": ".avif", "image/heic": ".heic",
        "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
        "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/mp4": ".m4a"}


def configure(per_host=None, pace_ms=None):
    with _lock:
        if per_host:
            _limits["per_host"] = max(1, int(per_host))
        if pace_ms is not None:
            _limits["pace"] = max(0, int(pace_ms)) / 1000.0


def _tls13():
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    return ctx


class _Tls13(HTTPAdapter):
    """Python's default TLS context, TLS 1.3 only. baraag.net answered 403
    and VerticalScope's forums 409 (or nothing) to urllib3's handshake, while
    this one, curl's and a browser's passed -- with the same honest headers."""

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = _tls13()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = _tls13()
        return super().proxy_manager_for(*args, **kwargs)


# Hosts (host[:port], as requests sends it) without TLS 1.3 get the usual
# handshake. They refuse 1.3 with an alert (gelbooru.com) or simply hang up
# (Amazon's older load balancers). An alert is proof at once, a hang-up only
# the second time: once may be a passing fault, and the fallback is the very
# handshake the bot checks refuse.
_OLD_TLS = set()
_hung_up = {}
_NO_TLS13 = ("PROTOCOL_VERSION", "UNSUPPORTED_PROTOCOL", "WRONG_VERSION_NUMBER", "NO_PROTOCOLS_AVAILABLE")


def _origin(url):
    p = urllib.parse.urlsplit(url)
    return p.scheme, p.hostname, p.port or (443 if p.scheme == "https" else 80)


class _Session(requests.Session):
    """requests drops a Cookie header of our own on every redirect, the same host's too, and builds the
    next hop's from its jar -- which holds none of a login that goes as a header (see _get). A forum
    that answers /forum/ with a 301 to /forum/index.php, and a bot check that challenges a request
    without cookies, then saw a visitor on the second hop: the login looked expired seconds after it was
    made. The header goes along again to the same place (scheme, host and port), and to no other."""

    def rebuild_auth(self, prepared_request, response):
        super().rebuild_auth(prepared_request, response)
        sent = response.request.headers.get("Cookie")
        if not sent or _origin(response.request.url) != _origin(prepared_request.url):
            return
        mine = {c.split("=", 1)[0].strip() for c in sent.split(";")}
        # What the answers set meanwhile (the jar's header) stays, unless it is a login cookie's name.
        extra = [c.strip() for c in (prepared_request.headers.get("Cookie") or "").split(";")
                 if c.strip() and c.split("=", 1)[0].strip() not in mine]
        prepared_request.headers["Cookie"] = "; ".join([sent] + extra)


def _session():
    s = getattr(_local, "session", None)
    if s is None:
        s = _local.session = _Session()
        s.headers["User-Agent"] = config.USER_AGENT
        s.mount("https://", _Tls13())
    for netloc in list(_OLD_TLS):
        if "https://%s/" % netloc not in s.adapters:
            s.mount("https://%s/" % netloc, HTTPAdapter())     # the longer prefix wins
    return s


_shared = None
_shared_lock = threading.Lock()


def _picture_session():
    """One session for every gallery picture, kept for good. A request of the page runs on a
    thread of its own, so _session() would build a fresh one -- a new TLS context and a new
    handshake -- for each of sixty thumbnails, and that was most of the wait. It takes no
    cookies: what a login needs goes per request (_get), and nothing leaks between hosts."""
    global _shared
    with _shared_lock:
        if _shared is None:
            s = _shared = requests.Session()
            s.headers["User-Agent"] = config.USER_AGENT
            s.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
            s.mount("https://", _Tls13(pool_connections=32, pool_maxsize=16))
        for netloc in list(_OLD_TLS):
            if "https://%s/" % netloc not in _shared.adapters:
                _shared.mount("https://%s/" % netloc, HTTPAdapter(pool_connections=4, pool_maxsize=16))
        return _shared


def _lacks_tls13(e, session):
    """Whether a failed handshake shows that its server -- the request's own or
    a redirect's -- speaks no TLS 1.3. Judged by what this attempt used: a
    thread that tried 1.3 while another one found out is not a second failure."""
    url = e.request.url if getattr(e, "request", None) is not None else ""
    netloc = urllib.parse.urlparse(url).netloc.lower()
    if not netloc or "CERTIFICATE" in str(e) or not isinstance(session.get_adapter(url), _Tls13):
        return False
    with _lock:
        if netloc not in _OLD_TLS:
            _hung_up[netloc] = _hung_up.get(netloc, 0) + 1
            if not any(m in str(e) for m in _NO_TLS13) and _hung_up[netloc] < 2:
                return False
            _OLD_TLS.add(netloc)
            log.info("%s speaks no TLS 1.3; using TLS 1.2 there", netloc)
    return True


class _Polite:
    """At most per_host requests to one host at a time, pace seconds apart --
    one at a time and LOGIN_PACE apart for requests carrying a login, timed
    from the end of the last one, with a reading break now and then."""

    def __init__(self, url, login=False, first=False, preview=False):
        # first: somebody is waiting for this one -- a gallery's large view, or a download they
        # asked for (interactive()). It goes ahead of what can wait and takes no reading break.
        self.token = login == "token"
        self.url, self.login = url, login is True
        self.first = first or bool(getattr(_local, "interactive", 0))
        self.preview = preview and not login
        self.host = urllib.parse.urlparse(url).hostname or ""

    def __enter__(self):
        _stopped(self.url)
        own = _own(self.host)
        with _lock:
            limit, pace = min(_limits["per_host"], own[0]), max(_limits["pace"], own[1])
            if self.login:                       # Settings can make this gentler, never faster
                limit, pace = 1, max(pace, LOGIN_PACE)
                if self.first:                   # somebody waits: the gap of a person browsing, not of a scan
                    pace = max(_limits["pace"], min(own[1], 1.0), INTERACTIVE_PACE)
            elif self.token:
                limit, pace = 1, max(pace, TOKEN_PACE if not self.first else 0.3)
            elif self.preview:
                limit, pace = PREVIEW
            lane = (self.host, self.login, self.preview, self.token)
            entry = _hosts.get(lane)
            if entry is None or entry["limit"] != limit:
                entry = _hosts[lane] = {
                    "sem": threading.BoundedSemaphore(limit), "limit": limit, "start": 0.0, "end": 0.0,
                    "count": 0, "break": random.randint(*READ_EVERY), "first": 0}
            self.entry = entry
            if self.first:
                entry["first"] += 1
        # A request somebody is looking at (the gallery's large view) goes before
        # those that can wait (the grid's pictures) -- the same slots, not more.
        while not self.first and entry["first"]:
            time.sleep(0.05)
        try:
            entry["sem"].acquire()
        finally:
            if self.first:
                with _lock:
                    entry["first"] -= 1
        try:
            with _lock:
                # One at a time: the gap runs from the end of the last request,
                # so a slow answer does not eat it.
                at = (entry["end"] if self.login else entry["start"]) + pace * random.uniform(*JITTER)
                if self.login:
                    entry["count"] += 1
                    if entry["count"] >= entry["break"] and not self.first:
                        entry["count"], entry["break"] = 0, random.randint(*READ_EVERY)
                        at += random.uniform(*READ_BREAK)
                now = time.monotonic()
                entry["start"] = max(at, now)
            if at > now:
                time.sleep(at - now)
            _stopped(self.url)                   # a pause may have begun meanwhile
        except BaseException:
            entry["sem"].release()
            raise
        return self

    def __exit__(self, *exc):
        self.entry["end"] = time.monotonic()
        self.entry["sem"].release()


def waiting():
    """True inside interactive(): somebody is waiting for what this thread asks."""
    return bool(getattr(_local, "interactive", 0))


@contextlib.contextmanager
def interactive():
    """Requests made while somebody waits for the answer (a download asked for in the
    gallery): ahead of those that can wait in a site's lane, and without the reading break
    a login lane takes now and then. The gaps between requests stay: they are the site's."""
    _local.interactive = getattr(_local, "interactive", 0) + 1
    try:
        yield
    finally:
        _local.interactive -= 1


@contextlib.contextmanager
def watching(fn):
    """fn(done, total) hears every chunk of the files this thread downloads (total 0: the site did not say) --
    the gallery's ring round a tile's download button."""
    before = getattr(_local, "watch", None)
    _local.watch = fn
    try:
        yield
    finally:
        _local.watch = before


def _own(host):
    """A host's own limits: its HOSTS entry, or its domain's (".twimg.com")."""
    if host in HOSTS:
        return HOSTS[host]
    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        if "." + ".".join(parts[i:]) in HOSTS:
            return HOSTS["." + ".".join(parts[i:])]
    return (99, 0)


def _retry_after(resp):
    """Seconds a site asks to wait: Retry-After (seconds or a date), Patreon's
    body, or Mastodon's X-RateLimit-Reset (a time). None when it says nothing."""
    value = (resp.headers.get("Retry-After") or "").strip()
    if value.isdigit():
        return int(value)
    if value:
        try:
            return max(0.0, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError):
            pass
    try:
        return int(resp.json()["errors"][0]["retry_after_seconds"])
    except Exception:
        pass
    reset = (resp.headers.get("X-RateLimit-Reset") or "").strip()
    if reset:
        try:
            when = float(reset) if reset.replace(".", "").isdigit() else \
                datetime.datetime.fromisoformat(reset.replace("Z", "+00:00")).timestamp()
            return max(0.0, when - time.time())
        except ValueError:
            pass
    return None


def _get(url, params=None, stream=False, headers=None, method="GET", data=None, json=None, tries=None,
         pooled=False):
    """A response, retrying what passes with time. The caller holds _Polite(url).

    A site the user logged in to gets what proves the login (accounts.py) --
    per request, never in the shared session, so it reaches no other host.
    Cookies go as a Cookie header of their own: requests' cookies= is sent in
    addition to what the session caught from earlier answers, and pixiv read
    its guest PHPSESSID from there first, so a logged-in sync silently ran as
    a guest. A POST (a login's token) is sent once, never repeated.

    A stop is never argued with: a bot check, a 409, a 429 on pixiv or on a
    login, a wait longer than CAP -- the site is paused and SlowDown raised.
    """
    login = _carries_login(url, headers, params) is True
    headers = dict(accounts.headers_for(url), **(headers or {}))
    host = urllib.parse.urlparse(url).hostname or ""
    tries = tries or (RETRIES if method == "GET" else 1)
    attempt = handshakes = 0
    while attempt < tries:
        session = _picture_session() if pooled else _session()
        if login:
            spend(url)
        try:
            resp = session.request(method, url, params=params, stream=stream, timeout=TIMEOUT,
                                   headers=headers, data=data, json=json)
            code = resp.status_code
            if resp.headers.get("cf-mitigated") == "challenge":
                resp.close()
                pause(url, _hours(6, 12), "it showed a bot check")
                raise SlowDown("%s showed a bot check; Sourcerer leaves it alone for some hours" % host)
            if code == 409 or "is_suspected_bot" in resp.headers.get("Set-Cookie", ""):
                pause(url, _hours(6, 12), "it took Sourcerer for a bot")
                resp.raise_for_status()
            # A 503 that stays after the retries: with a single try (a gallery picture) one
            # transient 503 says nothing, and resting a whole site for it would stop its syncs.
            if code == 429 or (code == 503 and tries > 1 and attempt == tries - 1):
                wait = _retry_after(resp)
                if host in STOP_HOSTS or login or attempt == tries - 1 or (wait or 0) > CAP:
                    resp.close()
                    pause(url, (wait or (_hours(6, 12) if host in STOP_HOSTS else _hours(1, 3))) *
                          random.uniform(1.05, 1.3), "it asked Sourcerer to slow down")
                    raise SlowDown("%s asked Sourcerer to slow down; it rests for a while" % host)
            if (code == 429 or code >= 500) and attempt < tries - 1:
                wait = _retry_after(resp)
                if (wait or 0) > CAP:               # a maintenance page's "come back in two hours"
                    resp.close()
                    pause(url, wait * random.uniform(1.05, 1.3), "it asked Sourcerer to slow down")
                    raise SlowDown("%s asked Sourcerer to slow down; it rests for a while" % host)
                resp.close()
                delay = (wait if wait is not None else 5 * 2 ** attempt) * random.uniform(1.0, 1.25)
                log.info("%s answered %s; waiting %ds", host, code, delay)
                time.sleep(delay)
                attempt += 1
                continue
            if login and code in (401, 403):
                _refusal(url, False)
            elif login and code < 400:
                _refusal(url, True)
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as e:
            if isinstance(e, requests.exceptions.SSLError):
                if "CERTIFICATE" in str(e):          # does not get better by asking again
                    raise
                if _lacks_tls13(e, session):
                    continue                     # the same attempt again, the old way
                if handshakes < 2:               # a failed handshake sent nothing: safe for a POST too
                    handshakes += 1
                    time.sleep(1)
                    continue
            if attempt >= tries - 1:
                raise
            time.sleep(3 * (attempt + 1) * random.uniform(1.0, 1.25))
            attempt += 1
    raise RuntimeError("no answer from %s" % url)


# Matched by its start: errors stored by older versions end differently.
LOGIN_PREFIX = "log in first"
LOGIN = LOGIN_PREFIX + ": Manage Accounts"


def level(e):
    """'warn' when a source works with a catch the user can act on or wait out
    (a login, a bot check, a site asking to slow down), 'error' when it does not."""
    if isinstance(e, SlowDown) or e.__class__.__name__ == "LoginRequired":
        return "warn"
    if isinstance(e, requests.HTTPError) and e.response is not None and \
            e.response.status_code in (401, 429):
        return "warn"
    return "error"


def reason(e):
    """A failed request in a few words, for a card's dot and the activity log."""
    if e.__class__.__name__ == "LoginRequired":
        return LOGIN
    if isinstance(e, SlowDown):
        return str(e)
    if isinstance(e, requests.HTTPError) and e.response is not None:
        code = e.response.status_code
        host = urllib.parse.urlparse(e.response.url or "").hostname or "the site"
        if code == 409 or "is_suspected_bot" in e.response.headers.get("Set-Cookie", ""):
            return "%s took Sourcerer for a bot and refused it (%d)" % (host, code)
        return {401: LOGIN + " (401)", 403: "%s refused access (403)" % host,
                404: "not found (404)", 410: "gone (410)",
                429: "too many requests (429)"}.get(code, "%s answered HTTP %d" % (host, code))
    if isinstance(e, requests.Timeout):
        return "no answer (timeout)"
    if isinstance(e, requests.ConnectionError):
        return "cannot connect"
    return str(e) or e.__class__.__name__


def get_json(url, params=None, headers=None):
    params = {k: v for k, v in (params or {}).items() if v is not None}
    with _Polite(url, _carries_login(url, headers, params)):
        return _get(url, params, headers=headers).json()


def post_read(url, json=None, headers=None):
    """A POST that only reads (Misskey's whole API is one): the site's ordinary lane, retried like a GET."""
    with _Polite(url, _carries_login(url, headers)):
        return _get(url, headers=headers, method="POST", json=json, tries=RETRIES).json()


def get_json_next(url, params=None, headers=None):
    """get_json and the next page's address from the Link header (Mastodon pages by it), or None.
    The address comes from the server: one on another host or without https would be sent the
    login's token, so it is not followed."""
    params = {k: v for k, v in (params or {}).items() if v is not None}
    with _Polite(url, _carries_login(url, headers, params)):
        resp = _get(url, params, headers=headers)
        found = (resp.links.get("next") or {}).get("url")
    here, there = urllib.parse.urlsplit(url), urllib.parse.urlsplit(found or "")
    return resp.json(), (found if there.scheme == "https" and there.netloc.lower() == here.netloc.lower() else None)


def public_https(url):
    """Whether url is an https address that leads out to the internet, not into this machine or its
    network -- for addresses a site hands out (an avatar, an account's home). The name is resolved
    here; a name that does not resolve is let through (a proxy may know it) and so is a redirect."""
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            return False
        for info in socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP):
            if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
                return False
    except socket.gaierror:
        return True
    except (OSError, ValueError):
        return False
    return True


def post_json(url, data=None, json=None, headers=None):
    """A login's request (a token, a session): sent once, the answer as JSON."""
    with _Polite(url, True):
        resp = _get(url, headers=headers, method="POST", data=data, json=json)
        return resp.json() if resp.content.strip() else {}     # Bluesky's deleteSession: nothing


def get_text(url, params=None, headers=None):
    """A page as text, for the sites that have no API (forums)."""
    with _Polite(url, _carries_login(url, headers, params)):
        resp = _get(url, params, headers=headers)
        return resp.text, resp.url


def extension(content_type, url="", fallback=".bin"):
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in _EXT:
        return _EXT[ctype]
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if 1 < len(ext) <= 5:
        return ext
    return mimetypes.guess_extension(ctype) or fallback


def _disposition_name(header):
    """The file name a server sends along (Content-Disposition), if any."""
    if not header:
        return ""
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", header, re.I)
    if m:
        return urllib.parse.unquote(m.group(1)).strip('" ')
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', header, re.I)
    return m.group(1).strip() if m else ""


def download(url, folder, mime_hint="", progress=None, headers=None):
    """Stream url into folder/<random>.part.

    Returns (part_path, sha256, extension, the server's file name or "").
    progress(n) is called with every chunk's size, for the speed shown.
    """
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (".%s.part" % os.urandom(6).hex())
    digest = hashlib.sha256()
    # The whole transfer counts against the site's limit, not just its start.
    with _Polite(url, _carries_login(url, headers)):
        return _stream(url, part, digest, mime_hint, progress, headers)


def _stream(url, part, digest, mime_hint, progress, headers):
    resp = _get(url, stream=True, headers=headers)
    try:
        # A web page where a file should be: a hotlink guard or a login wall,
        # never something to keep under a picture's name.
        if (resp.headers.get("Content-Type") or "").startswith("text/html") and \
                not mime_hint.startswith("text/html"):
            raise RuntimeError("%s sent a web page instead of the file" % urllib.parse.urlparse(url).hostname)
        ext = extension(resp.headers.get("Content-Type") or mime_hint, url)
        name = _disposition_name(resp.headers.get("Content-Disposition"))
        watch, done = getattr(_local, "watch", None), 0
        try:
            total = int(resp.headers.get("Content-Length") or 0)
        except ValueError:
            total = 0
        with open(part, "wb") as out:
            for chunk in resp.iter_content(1 << 16):
                digest.update(chunk)
                out.write(chunk)
                if progress:
                    progress(len(chunk))
                if watch:
                    done += len(chunk)
                    watch(done, total)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    finally:
        resp.close()
    return part, digest.hexdigest(), ext, name


def fetch_picture(url, headers=None, limit=40 << 20, first=False):
    """A picture or video for the gallery, as (content type, bytes): asked for
    once, no retries -- a preview is not worth asking a site twice -- and only
    a picture or a video is accepted."""
    with _Polite(url, _carries_login(url, headers), first, preview=not first):
        resp = _get(url, stream=True, headers=headers, tries=1, pooled=True)
        try:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not ctype.startswith(("image/", "video/")):
                raise RuntimeError("%s sent no picture" % urllib.parse.urlparse(url).hostname)
            data = resp.raw.read(limit + 1, decode_content=True)
        finally:
            resp.close()
    if len(data) > limit:
        raise ValueError("file too large")
    return ctype, data


def fetch_bytes(url, limit=10 << 20, headers=None):
    """A small file (a profile picture) as bytes."""
    with _Polite(url, _carries_login(url, headers)):
        resp = _get(url, stream=True, headers=headers)
        try:
            data = resp.raw.read(limit + 1, decode_content=True)
        finally:
            resp.close()
    if len(data) > limit:
        raise ValueError("file too large")
    return data
