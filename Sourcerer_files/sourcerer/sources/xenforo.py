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
import datetime
import html
import json
import logging
import random
import re
import urllib.parse

import requests

from . import _gdl
from .. import accounts, config, net

log = logging.getLogger(__name__)
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
# The title is the picture's alt text in the listing, which gallery-dl cuts into filename and extension ("IMG_1234.jpg"): no request.
# The date is the time of its tile in the page (gdl_run.py's "xenforo" mode adds it; a gallery-dl without it, or a page that shows
# none, says null).
FIELDS = {"url": "{_url!j}", "id": "{id!j}", "title": "{filename!j}", "ext": "{extension!j}", "date": "{date!j}"}
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
    return _page_info(media.post_url)


def _page_info(post_url):
    text, _final = net.get_text(post_url)
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


# The dates of a forum's pictures, by (host, id): the tile's own, the picture's page, or an estimate between two of those.
_dated = {}
MAX_DATED = 20000


def _post(f):
    return f["url"].rsplit("/full", 1)[0] + "/" if "/full" in f["url"] else f["url"]


def _epoch(text):
    try:
        return datetime.datetime.fromisoformat(_when(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


ASKS = 7                  # pages a batch of twenty may cost for its dates: the ends, then the middle of the widest gap
CLOSE = 2 * 86400         # a gap between two known times this narrow (seconds) is not asked into: the id between them is good enough


def _fill_dates(host, batch):
    """Dates for the pictures of a batch whose tile showed none (the list page of many forums shows no time at all). A picture's page has
    the exact time -- one request each, which a gallery of hundreds cannot ask for. A forum numbers its media as it goes, so the id is a
    clock that only runs forward: the time of the batch's lowest and highest id is read from their own pages, then of the middle one of the
    widest gap between two known times, until the gaps are under two days or ASKS pages were read; the pictures between are placed by their
    id, which cannot be wrong by more than the gap they sit in. Done only where somebody waits (an artist's gallery: net.waiting) and never
    for a sync; whatever is known is kept (_dated) and the next listing asks for nothing it knows. Any trouble -- the forum rests, wants a
    login, says no time -- leaves the pictures as they are (undated, or estimated from what was read)."""
    rows = []
    for f in batch:
        try:
            n = int(f.get("id"))
        except (TypeError, ValueError):
            continue
        when = _when(f.get("date"))
        if when:
            f["date"] = _dated[(host, n)] = when
        elif (host, n) in _dated:
            f["date"] = _dated[(host, n)]
        else:
            rows.append((n, f))
    if not rows or not net.waiting():
        return
    rows.sort(key=lambda r: r[0])
    anchors, asked = {}, [0]

    def ask(n, f):
        try:
            when = _when(_page_info(_post(f)).get("posted"))
        except Exception as e:
            log.info("%s: no date for picture %s: %s", host, n, net.reason(e))
            return False
        asked[0] += 1
        if not when or _epoch(when) is None:
            return False
        f["date"] = _dated[(host, n)] = when
        anchors[n] = _epoch(when)
        return True

    for n, f in (rows[:1] + rows[-1:] if len(rows) > 1 else rows):
        if not ask(n, f):
            return
    while asked[0] < ASKS:
        ns = sorted(anchors)
        gaps = [(abs(anchors[b] - anchors[a]), a, b) for a, b in zip(ns, ns[1:])
                if any(a < n < b and not f.get("date") for n, f in rows)]
        if not gaps or max(gaps)[0] <= CLOSE:
            break
        _, a, b = max(gaps)
        between = [(n, f) for n, f in rows if a < n < b and not f.get("date")]
        if not ask(*between[len(between) // 2]):
            break
    ns = sorted(anchors)
    for n, f in rows:
        if f.get("date") or not ns:
            continue
        lo = max((a for a in ns if a < n), default=ns[0])
        hi = min((b for b in ns if b > n), default=ns[-1])
        t = anchors[lo] + (anchors[hi] - anchors[lo]) * (n - lo) / (hi - lo) if hi != lo else anchors[lo]
        f["date"] = _dated[(host, n)] = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if len(_dated) > MAX_DATED:
        _dated.clear()


def _title(f):
    """The picture's name as the list shows it: the alt text, which is the title the uploader's file name became ("IMG_1234.jpg") --
    gallery-dl cuts it at the last dot, so it is put back together; the id when the list says nothing."""
    title, ext = (f.get("title") or "").strip(), (f.get("ext") or "").strip()
    return (title + "." + ext if title and ext else title) or str(f["id"])


def _when(text):
    """The time a tile shows as ISO ("2020-05-01T12:00:00+0000" has no colon in its offset, which older Pythons do not read), or ""."""
    text = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", str(text or "").strip())
    return text if re.match(r"\d{4}-\d\d-\d\d", text) else ""


def pages(url):
    from . import LoginRequired, Media
    if not _gdl.available():
        raise RuntimeError("Forums need gallery-dl, which did not install: Settings > Repair")
    host = _host(url)
    net._stopped(url)
    listing = _gdl.items(url, None, _options(url), FIELDS, lock="xenforo:" + host, trace="xenforo")
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
        batch = [f for f in batch if f.get("id") and f.get("url")]
        _fill_dates(host, batch)
        yield [Media(remote_key="xenforo:%s:%s" % (host, f["id"]), url=f["url"],
                     post_url=_post(f),
                     # the title is the file name's last resort and what a tile says (the forum's own name for the file
                     # comes with the download, and wins)
                     posted=_when(f.get("date")), name=_title(f),
                     # The forum shows its files to members only: the gallery fetches
                     # them through Sourcerer, with the login, and makes its own small copy.
                     large=f["url"], preview_headers={})
               for f in batch]
