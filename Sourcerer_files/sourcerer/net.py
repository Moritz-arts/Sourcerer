"""HTTP: JSON requests and streamed downloads, polite to every site.

Speed comes from reusing connections (one requests.Session per thread, so a
new file costs no new TLS handshake) and from downloading several files at
once. Politeness comes from two limits per site: how many requests run at
once, and a pause between two of them -- Settings' values, or a site's own
stricter ones (HOSTS). A 429 or 5xx is waited out, honouring Retry-After,
except on the hosts in STOP_HOSTS: there the source stops and the next sync
carries on. Sourcerer says who it is in its User-Agent and never pretends to
be a browser on the public APIs it uses.
"""
import hashlib
import logging
import mimetypes
import os
import re
import threading
import time
import urllib.parse

import requests

from . import accounts, config

log = logging.getLogger(__name__)
TIMEOUT = (15, 60)          # connect, read
RETRIES = 4

_local = threading.local()
_lock = threading.Lock()
_hosts = {}                 # host -> [semaphore, limit, last request time]
_limits = {"per_host": 2, "pace": 0.25}

# Sites stricter than Settings: (requests at once, seconds apart). With
# Settings, the gentler of the two wins.
HOSTS = {"www.pixiv.net": (1, 1.5), "i.pximg.net": (2, 0.4), "www.patreon.com": (1, 1.0)}
# Not retried on a 429 or a bot check. pixiv's terms forbid "large numbers of
# actions within a short period"; tools that kept retrying there had accounts restricted.
STOP_HOSTS = {"www.pixiv.net"}


class SlowDown(Exception):
    """A site asked Sourcerer to stop for now: a 429 on a STOP_HOSTS host, or a bot check."""

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


def _session():
    s = getattr(_local, "session", None)
    if s is None:
        s = _local.session = requests.Session()
        s.headers["User-Agent"] = config.USER_AGENT
    return s


class _Polite:
    """At most per_host requests to one host at a time, pace seconds apart."""

    def __init__(self, url):
        self.host = urllib.parse.urlparse(url).hostname or ""

    def __enter__(self):
        own = HOSTS.get(self.host, (99, 0))
        with _lock:
            limit, pace = min(_limits["per_host"], own[0]), max(_limits["pace"], own[1])
            entry = _hosts.get(self.host)
            if entry is None or entry[1] != limit:
                entry = _hosts[self.host] = [threading.BoundedSemaphore(limit), limit, 0.0]
            self.sem = entry[0]
        self.sem.acquire()
        with _lock:
            wait = entry[2] + pace - time.monotonic()
            entry[2] = max(entry[2] + pace, time.monotonic())
        if wait > 0:
            time.sleep(wait)
        return self

    def __exit__(self, *exc):
        self.sem.release()


def _get(url, params=None, stream=False, headers=None):
    """A response, retrying what passes with time. The caller holds _Polite(url).

    A site the user logged in to gets its saved cookies (accounts.py) -- per
    request, never in the shared session, so they reach no other host. As a
    Cookie header of their own: requests' cookies= is sent in addition to what
    the session caught from earlier answers, and pixiv read its guest
    PHPSESSID from there first, so a logged-in sync silently ran as a guest.
    """
    jar = accounts.cookies_for(url)
    if jar:
        headers = dict(headers or {}, Cookie="; ".join("%s=%s" % kv for kv in jar.items()))
    ua = accounts.user_agent_for(url)          # a Cloudflare pass holds only with its browser's
    if ua:
        headers = dict(headers or {}, **{"User-Agent": ua})
    host = urllib.parse.urlparse(url).hostname or ""
    for attempt in range(RETRIES):
        try:
            resp = _session().get(url, params=params, stream=stream, timeout=TIMEOUT,
                                  headers=headers)
            if resp.headers.get("cf-mitigated") == "challenge":
                resp.close()
                raise SlowDown("%s showed a bot check; the next sync tries again" % host)
            if resp.status_code == 429 and host in STOP_HOSTS:
                resp.close()
                raise SlowDown("%s asks Sourcerer to slow down; the next sync carries on" % host)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == RETRIES - 1:
                    resp.raise_for_status()
                wait = resp.headers.get("Retry-After", "")
                try:          # Patreon says it in the body: errors[0].retry_after_seconds
                    wait = wait or str(int(resp.json()["errors"][0]["retry_after_seconds"]))
                except Exception:
                    pass
                resp.close()
                delay = min(int(wait), 300) if wait.isdigit() else 5 * 2 ** attempt
                log.info("%s answered %s; waiting %ss", urllib.parse.urlparse(url).hostname,
                         resp.status_code, delay)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout):
            if attempt == RETRIES - 1:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("no answer from %s" % url)


LOGIN = "log in first: Settings > Accounts"


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
    with _Polite(url):
        return _get(url, params, headers=headers).json()


def get_text(url, params=None, headers=None):
    """A page as text, for the sites that have no API (forums)."""
    with _Polite(url):
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
    with _Polite(url):
        return _stream(url, part, digest, mime_hint, progress, headers)


def _stream(url, part, digest, mime_hint, progress, headers):
    resp = _get(url, stream=True, headers=headers)
    try:
        ext = extension(resp.headers.get("Content-Type") or mime_hint, url)
        name = _disposition_name(resp.headers.get("Content-Disposition"))
        with open(part, "wb") as out:
            for chunk in resp.iter_content(1 << 16):
                digest.update(chunk)
                out.write(chunk)
                if progress:
                    progress(len(chunk))
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    finally:
        resp.close()
    return part, digest.hexdigest(), ext, name


def fetch_bytes(url, limit=10 << 20, headers=None):
    """A small file (a profile picture) as bytes."""
    with _Polite(url):
        resp = _get(url, stream=True, headers=headers)
        try:
            data = resp.raw.read(limit + 1, decode_content=True)
        finally:
            resp.close()
    if len(data) > limit:
        raise ValueError("file too large")
    return data
