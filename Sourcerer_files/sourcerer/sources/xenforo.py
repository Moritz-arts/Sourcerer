"""XenForo forums: a member's media gallery (XenForo Media Gallery), an album,
or a thread's attachments. Most forums show their media to members only:
log in to the forum under Manage Accounts.

Listing goes through gallery-dl's generic XenForo extractor (_gdl.py, with
the "xenforo:" prefix that makes it work on any forum); the files are the
/full originals, downloaded by Sourcerer itself -- their Content-Disposition
carries the uploader's file name, where gallery-dl only knows the title.

Many forums sit behind a bot check that lets only browsers through. The
login window is one: its cookies -- Cloudflare's pass among them -- and its
User-Agent go along with every request to the forum (accounts.py).
"""
import html
import re
import urllib.parse

import requests

from . import _gdl
from .. import accounts, config, net

KIND = "xenforo"
LABEL = "XenForo"
# What a XenForo link points at, below the forum's base (which may be a folder).
_PATH = re.compile(r"^(.*?)/(?:index\.php\?)?(media/users|members|media/albums|threads)/([^/?#]+)", re.I)
# tls12: off, so gallery-dl shakes hands with TLS 1.3 only, as net.py does --
# VerticalScope's forums answered its usual handshake with 409 (see net._Tls13).
OPTIONS = {"sleep-request": "2.0-5.0", "metadata": False, "tls12": False}
FIELDS = {"url": "{_url!j}", "id": "{id!j}"}
LOGIN = ("recommended", "Most forums show their media to members only.")


def _parts(url):
    p = urllib.parse.urlparse(url.strip())
    m = _PATH.match(p.path + ("?" + p.query if p.query else ""))
    return (p, m) if m and p.hostname else (p, None)


def match(url):
    p, m = _parts(url)
    # A slug.id is XenForo's mark; other forum software names its pages differently.
    return bool(m and re.search(r"\.\d+$", m.group(3)))


def normalize(url):
    """A member's media gallery for a member's link; albums and threads as they are."""
    p, m = _parts(url)
    kind = m.group(2).lower()
    if kind == "members":
        kind = "media/users"
    return "https://%s%s/%s/%s" % (p.netloc.lower(), m.group(1).rstrip("/"), kind, m.group(3))


def account_key(url):
    return "xenforo:" + _host(url)


def still_logged_in(key):
    base = (accounts.load(key) or {}).get("base") or "https://" + key.split(":", 1)[1]
    text, _final = net.get_text(base + "/")
    return 'data-logged-in="true"' in text


def _host(url):
    return accounts.host_of(url)


def _options(url):
    options = dict(OPTIONS, cookies=accounts.jar("xenforo:" + _host(url)))
    # The forum's own pass (Cloudflare) holds only with the browser that earned it.
    options.update({"user-agent": accounts.headers_for(url).get("User-Agent") or config.USER_AGENT,
                    "browser": ""})
    if "/threads/" in url:
        options["order-posts"] = "desc"          # newest first, for the early stop
    return options


def profile(url):
    """The member's name and picture, from their media page."""
    p, m = _parts(url)
    slug = m.group(3).rsplit(".", 1)[0]
    try:
        text, _final = net.get_text(url)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            from . import LoginRequired
            if "Log in" in (e.response.text or "") or not accounts.logged_in("xenforo:" + _host(url)):
                raise LoginRequired("this forum shows it to members only") from e
        raise
    title = re.search(r'<h1 class="p-title-value"[^>]*>(.*?)</h1>', text, re.S)
    name = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else slug
    name = re.sub(r"^Media added by\s+", "", html.unescape(name)) or slug
    avatar = re.search(r'<img src="([^"]+/avatars/[lmo]/[^"]+)"', text)
    return {"name": name, "handle": "%s on %s" % (slug, p.hostname),
            "avatar": urllib.parse.urljoin(url, html.unescape(avatar.group(1))) if avatar else ""}


def pages(url):
    from . import LoginRequired, Media
    if not _gdl.available():
        raise RuntimeError("Forums need gallery-dl, which did not install: Settings > Repair")
    host = _host(url)
    net._stopped(url)
    listing = _gdl.items("xenforo:" + url, urllib.parse.urlparse(url).hostname, _options(url), FIELDS)
    while True:
        try:
            batch = next(listing)
        except StopIteration:
            return
        except _gdl.Failed as e:
            if e.slow or "409" in str(e):
                net.pause(url, 6 * 3600, "it let only a browser through")
                raise net.SlowDown("%s let only a browser through: log in to it under Manage "
                                   "Accounts, so Sourcerer can use your login window's pass" % host) from e
            if e.auth or "403" in str(e):
                raise LoginRequired("this forum shows it to members only") from e
            raise
        yield [Media(remote_key="xenforo:%s:%s" % (host, f["id"]), url=f["url"],
                     post_url=f["url"].rsplit("/full", 1)[0] + "/" if "/full" in f["url"] else f["url"],
                     posted="", name=str(f["id"]),
                     # The forum shows its files to members only: the gallery fetches
                     # them through Sourcerer, with the login, and makes its own small copy.
                     large=f["url"], preview_headers={})
               for f in batch if f.get("id") and f.get("url")]
