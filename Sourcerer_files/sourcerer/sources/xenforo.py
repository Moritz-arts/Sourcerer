"""XenForo forums: a member's media gallery (XenForo Media Gallery), an album,
or a thread's attachments. Most forums show their media to members only:
log in to the forum under Manage Accounts.

Listing goes through gallery-dl's XenForo extractor (_gdl.py). The forum is made known to it by
its base (_options): the "xenforo:<url>" form takes only scheme and host as the forum, so a forum
in a folder (example.com/forum/) lost the folder and was asked at the wrong place. The files are the
/full originals, downloaded by Sourcerer itself -- their Content-Disposition
carries the uploader's file name, where gallery-dl only knows the title.

Many forums sit behind a bot check that lets only browsers through. The
login window is one: its cookies -- Cloudflare's pass among them -- and its
User-Agent go along with every request to the forum (accounts.py).
"""
import html
import json
import random
import re
import urllib.parse

import requests

from . import _gdl
from .. import accounts, config, net

KIND = "xenforo"
LABEL = "XenForo"
# What a XenForo link points at, below the forum's base (which may be a folder): the base, the route's
# "index.php?" when the link has it, the kind and the slug.id. A forum behind a guard that lets only "/"
# and "index.php?*" through answers the friendly path with a bare 403, so a link keeps the route it came with.
_PATH = re.compile(r"^(.*?)/(index\.php\?)?(media/users|members|media/albums|threads)/([^/?#]+)", re.I)
# tls12: off, so gallery-dl shakes hands with TLS 1.3 only, as net.py does --
# VerticalScope's forums answered its usual handshake with 409 (see net._Tls13).
# retries: 0 -- gallery-dl would answer a 429 with four more requests, with the login.
OPTIONS = {"sleep-request": "2.0-5.0", "metadata": False, "tls12": False, "retries": 0}
FIELDS = {"url": "{_url!j}", "id": "{id!j}", "title": "{filename!j}"}      # the title is the picture's alt text in the listing: no request
LOGIN = ("recommended", "Most forums show their media to members only.")


def _parts(url):
    p = urllib.parse.urlparse(url.strip())
    m = _PATH.match(p.path + ("?" + p.query if p.query else ""))
    return (p, m) if m and p.hostname else (p, None)


def match(url):
    p, m = _parts(url)
    # A slug.id is XenForo's mark; other forum software names its pages differently.
    return bool(m and re.search(r"\.\d+$", m.group(4)))


def normalize(url):
    """A member's media gallery for a member's link; albums and threads as they are."""
    p, m = _parts(url)
    kind = m.group(3).lower()
    if kind == "members":
        kind = "media/users"
    return "https://%s%s/%s%s/%s" % (p.netloc.lower(), m.group(1).rstrip("/"), (m.group(2) or "").lower(), kind, m.group(4))


def account_key(url):
    return "xenforo:" + _host(url)


def still_logged_in(key):
    base = (accounts.load(key) or {}).get("base") or "https://" + key.split(":", 1)[1]
    text, _final = net.get_text(base + "/")
    return 'data-logged-in="true"' in text


def _host(url):
    return accounts.host_of(url)


def _options(url):
    """What gallery-dl gets for this forum (extractor-wide: see _gdl._config): the login, the pacing, and the
    forum's base registered as an instance of its own, which is what makes a forum it does not know by name
    -- or one in a folder -- match at all. The key must differ from every name gallery-dl knows."""
    p, m = _parts(url)
    options = dict(OPTIONS, cookies=accounts.jar("xenforo:" + _host(url), fresh=True),
                   xenforo={"sourcerer-" + _host(url): {"root": "%s://%s%s" % (p.scheme, p.netloc.lower(), m.group(1).rstrip("/"))}})
    # The forum's own pass (Cloudflare) holds only with the browser that earned it.
    options.update({"user-agent": accounts.headers_for(url).get("User-Agent") or config.USER_AGENT,
                    "browser": ""})
    if re.search(r"[/?]threads/", url):
        options["order-posts"] = "desc"          # newest first, for the early stop
    return options


def account_name(url):
    """The member in a link as words -- "john-doe.12" is "john doe" -- for a card made without a name. (A forum that routes through
    `index.php?` has the member in the query, so the last part of the path says "index.php".)"""
    p, m = _parts(url)
    if not m:
        return ""
    slug = urllib.parse.unquote(m.group(4)).rsplit(".", 1)[0]
    return re.sub(r"[-_]+", " ", slug).strip()


def _jsonld(page):
    """The page's schema.org block (XenForo writes one on member pages and on media items), or {}."""
    for quote in ('"', "'"):
        raw = re.search(r"<script type=%sapplication/ld\+json%s>(.*?)</script>" % (quote, quote), page, re.S)
        if raw:
            try:
                data = json.loads(raw.group(1))
                return data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else {}
            except ValueError:
                return {}
    return {}


def _members_only(e, url):
    from . import LoginRequired
    if e.response is not None and e.response.status_code in (401, 403):
        if "Log in" in (e.response.text or "") or not accounts.logged_in("xenforo:" + _host(url)):
            raise LoginRequired("this forum shows it to members only") from e


def profile(url):
    """The member's name and picture. A member's own page says both in its schema block (name, image) -- and in og:image, for a
    forum that writes no schema; an album or a thread has no member, and its title says what it is."""
    p, m = _parts(url)
    slug = m.group(4).rsplit(".", 1)[0]
    kind = m.group(3).lower()
    handle = "%s on %s" % (slug, p.hostname)
    if kind in ("members", "media/users"):
        page = "https://%s%s/%smembers/%s/" % (p.netloc.lower(), m.group(1).rstrip("/"), m.group(2) or "", m.group(4))
        try:
            text, _final = net.get_text(page)
        except requests.HTTPError as e:
            _members_only(e, url)
            raise
        main = _jsonld(text).get("mainEntity") or {}
        name = html.unescape(main.get("name") or "").strip()
        if not name:
            og = re.search(r'<meta property="og:title" content="([^"]*)"', text)
            name = html.unescape(og.group(1)).split(" | ")[0].strip() if og else ""
        picture = main.get("image") or ""
        if not picture:
            og = re.search(r'<meta property="og:image" content="([^"]*/avatars/[^"]*)"', text) or \
                 re.search(r'<img src="([^"]+/avatars/[lmo]/[^"]+)"', text)
            picture = html.unescape(og.group(1)) if og else ""
        if name or picture:
            return {"name": name or slug, "handle": handle, "avatar": urllib.parse.urljoin(page, picture) if picture else ""}
    try:
        text, _final = net.get_text(url)
    except requests.HTTPError as e:
        _members_only(e, url)
        raise
    title = re.search(r'<h1 class="p-title-value"[^>]*>(.*?)</h1>', text, re.S)
    name = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else slug
    name = re.sub(r"^Media added by\s+", "", html.unescape(name)) or slug
    avatar = re.search(r'<img src="([^"]+/avatars/[lmo]/[^"]+)"', text)
    return {"name": name, "handle": handle,
            "avatar": urllib.parse.urljoin(url, html.unescape(avatar.group(1))) if avatar else ""}


def info(media):
    """What the forum knows of one picture -- its title, description, who and when, size, views -- from the picture's own page: one
    request, asked when the viewer opens it (a listing page holds a title only; gallery-dl's `metadata` would ask for every
    picture of it). {} when the page says nothing."""
    text, _final = net.get_text(media.post_url)
    schema = _jsonld(text)
    main = schema.get("mainEntity") or schema

    def number(x):
        m = re.match(r"\s*(\d+)", str((x.get("name") if isinstance(x, dict) else x) or ""))
        return int(m.group(1)) if m else 0

    stats = {}
    for st in main.get("interactionStatistic") or []:
        kind = str((st.get("interactionType") or {}).get("@type") if isinstance(st.get("interactionType"), dict) else st.get("interactionType") or "")
        for word, key in (("View", "views"), ("Like", "likes"), ("Comment", "comments")):
            if word in kind:
                stats[key] = st.get("userInteractionCount")
    author = main.get("author")
    out = {"title": html.unescape(main.get("name") or ""), "description": html.unescape(main.get("description") or ""),
           "posted": re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", main.get("dateCreated") or ""),      # +0000 is not an ISO offset to every parser "author": html.unescape((author.get("name") if isinstance(author, dict) else author) or ""),
           "size": main.get("contentSize") or "", "width": number(main.get("width")), "height": number(main.get("height"))}
    out.update(stats)
    return {k: v for k, v in out.items() if v not in ("", 0, None)}


def pages(url):
    from . import LoginRequired, Media
    if not _gdl.available():
        raise RuntimeError("Forums need gallery-dl, which did not install: Settings > Repair")
    host = _host(url)
    net._stopped(url)
    listing = _gdl.items(url, None, _options(url), FIELDS, lock="xenforo:" + host)
    while True:
        try:
            batch = next(listing)
        except StopIteration:
            return
        except _gdl.Failed as e:
            # The status, not the digits: a thread id may contain 409.
            status = re.search(r"'(\d{3}) ", str(e))
            status = status.group(1) if status else ""
            if status == "429" or (e.slow and status != "409"):
                net.pause(url, random.uniform(1, 3) * 3600, "it asked Sourcerer to slow down")
                raise net.SlowDown("%s asked Sourcerer to slow down; it rests for a while" % host) from e
            if e.slow or status == "409":
                net.pause(url, 6 * 3600, "it let only a browser through")
                raise net.SlowDown("%s let only a browser through: log in to it under Manage "
                                   "Accounts, so Sourcerer can use your login window's pass" % host) from e
            if e.auth or status == "403":
                raise LoginRequired("this forum shows it to members only") from e
            raise
        yield [Media(remote_key="xenforo:%s:%s" % (host, f["id"]), url=f["url"],
                     post_url=f["url"].rsplit("/full", 1)[0] + "/" if "/full" in f["url"] else f["url"],
                     # the title is the file name's last resort and what a tile says (the forum's own name for the file
                     # comes with the download, and wins)
                     posted="", name=(f.get("title") or "").strip() or str(f["id"]),
                     # The forum shows its files to members only: the gallery fetches
                     # them through Sourcerer, with the login, and makes its own small copy.
                     large=f["url"], preview_headers={})
               for f in batch if f.get("id") and f.get("url")]
