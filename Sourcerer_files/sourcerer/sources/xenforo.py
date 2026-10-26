"""XenForo forums: a member's media gallery (XenForo Media Gallery), an album,
or a thread's attachments. Most forums show their media to members only:
log in to the forum under Manage Accounts.

Listing goes through gallery-dl's XenForo extractor (_gdl.py). The forum is made known to it by
its base (_options): the "xenforo:<url>" form takes only scheme and host as the forum, so a forum
in a folder (example.com/forum/) lost the folder and was asked at the wrong place. The files are the
/full originals, downloaded by Sourcerer itself -- their Content-Disposition
carries the uploader's file name, where gallery-dl only knows the title.

A forum without the Media Gallery addon has no media gallery to list: its member pages answer 404 and
a member's media sits in an attachment browser (an addon: one tile per attached file, whole posts newest
first). pages() asks once per forum whether the gallery exists and, where there is none, walks that
browser itself (_attachment_pages) -- no gallery-dl -- and dates its files by the posts they sit in:
a post's page shows its time above its files, the tile shows none.

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
import threading
import urllib.parse

import requests

from . import _gdl
from .. import accounts, config, db, net

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
OPEN_SLEEP = "1.5-3.0"   # ... while somebody waits for the page (an artist's gallery): faster, but a forum is no X (no daily budget, bot checks): never under 1.5 s
# The title is the picture's alt text in the listing, which gallery-dl cuts into filename and extension ("IMG_1234.jpg"): no request.
# The date is the time of its tile in the page (gdl_run.py's "xenforo" mode adds it; a gallery-dl without it, or a page that shows
# none, says null).
FIELDS = {"url": "{_url!j}", "id": "{id!j}", "title": "{filename!j}", "ext": "{extension!j}", "date": "{date!j}"}
LOGIN = ("recommended", "Most forums show their media to members only.")
FOLLOWS_HOURS = 11       # follows.py reads a forum's list of followed members at most this often (Fanbox's and Fantia's pace)
MAX_FOLLOW_PAGES = 200   # 4 000 follows: a forum that never ends its list is the forum's fault


def _parts(url):
    p = urllib.parse.urlparse(url.strip())
    m = _PATH.match(p.path + ("?" + p.query if p.query else ""))
    return (p, m) if m and p.hostname else (p, None)


def match(url):
    p, m = _parts(url)
    # A slug.id is XenForo's mark; other forum software names its pages differently. A forum that leaves the name out of
    # the address (`members/12`) is known by the member route alone -- its follow list names members so.
    return bool(m and (re.search(r"\.\d+$", m.group(4)) or (m.group(3).lower() == "members" and m.group(4).isdigit())))


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
    if net.waiting():
        options["sleep-request"] = OPEN_SLEEP
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


# ---- the members this login follows ----------------------------------------------------------------

# A follow list's rows: the link to a name and the link to that member's profile picture each carry
# `data-user-id`, so a row is put together by that id and not by where the two sit on the page -- a theme moves
# them apart, and a member without a picture has no picture link at all (the forum draws their initials). The
# login's own name sits on the same page, in the account bar, so rows come from the `username` links and the
# login's own id is left out.
_LINK = re.compile(r"<a\b[^>]*>", re.I)
_ID = re.compile(r'data-user-id="(\d+)"')
_HREF = re.compile(r'href="([^"]+)"')
_IMG = re.compile(r"<img\b[^>]*>", re.I)
# a theme that hangs the row's picture on a class instead of a data-user-id: `class="avatar-u12-s"`
_AVATAR_UID = re.compile(r'class="avatar-u(\d+)[-_]', re.I)
# The login's own member id, from the account page: `members/<name>.<id>`, or `members/<id>` on a
# forum that does not put the name in the address (example.com).
_ME = re.compile(r"members/([a-z0-9_.-]+\.\d+|\d+)", re.I)
# A forum page is a forum page: it loads its own stylesheet and carries XenForo's own markers. The bot check
# answers 200 with a page of its own -- a title of "<host> | Verification", no rows -- so nothing raises and an
# empty list would be read as "this account follows nobody".
_FORUM = re.compile(r"css\.php\?css=public|data-xf-init", re.I)


def _wall(text, host):
    """Stop when the answer is the forum's guard instead of the page: the login ran out, or Sourcerer is being
    checked. `net.get_text` cannot tell the two apart -- a check answers 200 with a page that has neither the
    forum's stylesheet nor XenForo's markers."""
    if not _FORUM.search(text):
        raise net.SlowDown("%s answered with a page of its own instead of the forum's: a bot check, or a login "
                           "that ran out" % host)


def _row_name(text, after):
    """The name inside a link: the template's tags off, the entities of a name with accents turned back."""
    end = text.find("</a>", after)
    return html.unescape(re.sub(r"<[^>]+>", "", text[after:end] if end > after else "")).strip()


def _row_picture(window, base):
    """The biggest profile picture a row links: XenForo puts the small one in `src` and a bigger one in `srcset` as
    its 2x. A member without a picture has none, and there is nothing to store."""
    found = re.search(r'srcset="([^"]+)"', window) or re.search(r'src="([^"]+)"', window)
    if not found:
        return ""
    biggest = found.group(1).split(",")[-1].strip().split()          # the last entry of a srcset is the largest
    return urllib.parse.urljoin(base, html.unescape(biggest[0])) if biggest else ""


def _rows(text, base, mine):
    """Every member a follow list names, in the order the page has them: [(profile address, name, picture)].
    `mine` is the login's own id -- the account bar names it on the same page, and it is not a follow."""
    named, picture = {}, {}
    for link in _LINK.finditer(text):
        tag = link.group(0)
        who = _ID.search(tag)
        if not who:
            continue
        uid = who.group(1)
        end = text.find("</a>", link.end())
        window = text[link.end():end] if end > link.end() else ""
        if 'class="username' in tag:
            href = _HREF.search(tag)
            if href and uid not in named:
                named[uid] = (urllib.parse.urljoin(base, html.unescape(href.group(1))),
                              _row_name(text, link.end()))
        elif 'class="avatar' in tag and uid not in picture:
            picture[uid] = _row_picture(window, base)
    # a theme that hangs the picture on a class rather than a data-user-id (`class="avatar-u12-s"`)
    for img in _IMG.finditer(text):
        tag = img.group(0)
        if 'class="avatar' not in tag:
            continue
        who = _ID.search(tag) or _AVATAR_UID.search(tag)
        if who and not picture.get(who.group(1)):
            picture[who.group(1)] = _row_picture(tag, base)
    return [(u, n, picture.get(uid, "")) for uid, (u, n) in named.items() if uid != mine]


def _member_of_login(base, host):
    """Which member the login is (`slug.id`): a follow list is a page of *someone's* follows, and a forum names the
    login nowhere else. `index.php?account/` says it -- one request per look, and it is not kept, because the same
    forum can be logged in as another account the next day and a kept id would then read that account's list."""
    text, _final = net.get_text("%s/index.php?account/" % base)
    who = _ME.search(text)
    if not who:
        _wall(text, host)
        raise net.SlowDown("%s did not say which member the login is: log in again in Manage Accounts" % host)
    return who.group(1)


def following(key):
    """(list name, pages) of the members this login follows: the page the follow list is on, the address a person
    clicks (`index.php?members/<me>/following/`). A forum puts the route in the query and prints no pagination for
    this list at all, so a page with fewer rows than the page before it is the last -- the forum's own end, not an
    empty page -- and the walk has a page cap. A row costs no extra request: its name and its profile picture come
    from the page it is listed on, and both are keyed by the id the row carries."""
    base = ((accounts.load(key) or {}).get("base") or ("https://" + key.split(":", 1)[1])).rstrip("/")
    host = urllib.parse.urlsplit(base).hostname or key

    def pages():
        me = _member_of_login(base, host)
        mine = me.rsplit(".", 1)[-1]
        full, seen = 0, set()
        for page in range(1, MAX_FOLLOW_PAGES + 1):
            # `&` before `page=`: the route lives in the query (`index.php?members/...`), the form every XenForo
            # answers even when its links use friendly URLs (see _PATH).
            url = "%s/index.php?members/%s/following/&" % (base, me)
            if page > 1:
                url += "page=%d" % page
            text, _final = net.get_text(url)
            rows = [r for r in _rows(text, base, mine) if r[0].lower() not in seen]
            if not rows:
                _wall(text, host)              # a challenge page has no rows: it does not mean "follows nobody"
                break
            seen.update(r[0].lower() for r in rows)
            yield [{"url": u, "name": n, "avatar": p} for u, n, p in rows]
            if full and len(rows) < full:
                break                          # no pagination printed: a page shorter than the one before is the last
            full = max(full, len(rows))
            if page == MAX_FOLLOW_PAGES:
                log.warning("%s: the list of followed members was cut at %d pages", host, MAX_FOLLOW_PAGES)

    yield ("following", pages())


def info(media):
    """What the forum knows of one picture -- its title, description, who and when, size, views -- from the picture's own page: one
    request, asked when the viewer opens it (a listing page holds a title only; gallery-dl's `metadata` would ask for every
    picture of it). {} when the page says nothing. A file of an attachment browser sits in a post of someone's thread, whose title,
    author and counts are not the file's: only the post's own time is given."""
    post = re.search(r"\bposts/(\d+)", media.post_url or "")
    if post:
        when = _post_times({"url": media.post_url}).get(post.group(1))
        return {"posted": when} if when else {}
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
           # (+0000 is not an ISO offset to every parser)
           "posted": re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", main.get("dateCreated") or ""), "author": html.unescape((author.get("name") if isinstance(author, dict) else author) or ""),
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


# What the exact times read so far say about the forum's clock, kept across listings and restarts (setting `xenforo_clock:<host>`): the
# media ids run on for the whole forum, so a time read for one member's picture dates another member's as well -- the first artist of a
# forum costs its asks, the second few, the tenth none. Exact times only: an estimate as an anchor would add its error to the next.
_clock, _clock_lock = {}, threading.Lock()
MAX_CLOCK = 3000          # anchors kept per forum: more are thinned out (every other one), so the whole range stays covered


def _anchors(host):
    """A copy of the exact times known for the forum (id -> epoch): the dict itself is shared by the threads of every gallery."""
    if host not in _clock:
        try:
            loaded = {int(k): float(v) for k, v in json.loads(db.get_setting("xenforo_clock:" + host, "{}")).items()}
        except (ValueError, TypeError, AttributeError):
            loaded = {}
        with _clock_lock:                       # (the setting is read outside the lock: a slow database must not stall every gallery)
            _clock.setdefault(host, loaded)
    with _clock_lock:
        return dict(_clock[host])


def _learn(host, learned):
    """Keep what a batch read (id -> epoch). Past MAX_CLOCK every other anchor goes -- never the lowest or the newest, which are the
    ends the next batch needs -- and the setting is written outside the lock."""
    with _clock_lock:
        known = _clock.setdefault(host, {})
        known.update(learned)
        if len(known) > MAX_CLOCK:
            for n in sorted(known)[1:-1:2]:
                del known[n]
        text = json.dumps(known)
    db.set_setting("xenforo_clock:" + host, text)


def _iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


ASKS = 7                  # pages a batch of twenty may cost for its dates: the ends, then the middle of the widest gap
CLOSE = 2 * 86400         # a gap between two known times this narrow (seconds) is not asked into: the id between them is good enough

def _fill_dates(host, batch, ordered=False, times=None):
    """Dates for the pictures of a batch whose tile showed none (the list page of many forums shows no time at all). A picture's page has
    the exact time -- one request each, which a gallery of hundreds cannot ask for. A forum numbers its media as it goes, so the id is a
    clock that only runs forward: the time of the batch's lowest and highest id is read from their own pages, then of the middle one of the
    widest gap between two known times, until the gaps are under two days or ASKS pages were read; the pictures between are placed by their
    id, which cannot be wrong by more than the gap they sit in. Done only where somebody waits (an artist's gallery: net.waiting) and never
    for a sync, nor when the forum is the gallery's only source *and* lists its pictures newest first by id (`ordered`, checked page by
    page in pages(): the ids only run forward, so the forum's own order is the order of their dates -- the first page used to wait for up to
    seven page requests; the viewer still shows the exact time when a picture opens). A forum that lists in another order is dated as ever; whatever is known is kept (_dated) and the next listing asks for nothing it knows. Any trouble -- the forum rests, wants a
    login, says no time -- leaves the pictures as they are (undated, or estimated from what was read). `host` names the clock: a forum
    whose files hang in posts is dated by the posts' own ids, a clock of its own (`<host>/posts`). `times(item)` says what asking about one
    item tells -- {id: time}, its own and any other the page carries -- where the item's page is not the media item's."""
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
    if not rows or not net.waiting() or (net.sole() and ordered):
        return
    known = _anchors(host)
    for n, f in rows:
        if n in known:
            f["date"] = _dated[(host, n)] = _iso(known[n])
    rows = sorted((r for r in rows if not r[1].get("date")), key=lambda r: r[0])
    if not rows:
        return
    anchors, asked, learned = dict(known), [0], {}

    def covered(n):
        """Known times on both sides of n that are close enough to place it: nothing to ask."""
        lo = max((a for a in anchors if a < n), default=None)
        hi = min((b for b in anchors if b > n), default=None)
        return lo is not None and hi is not None and abs(anchors[hi] - anchors[lo]) <= CLOSE

    by_id = dict(rows)

    def ask(n, f):
        try:
            told = times(f) if times else {str(n): _page_info(_post(f)).get("posted")}
        except Exception as e:
            log.info("%s: no date for picture %s: %s", host, n, net.reason(e))
            return False
        asked[0] += 1
        for k, v in told.items():                # (the page of one post carries its neighbours' times too: each one is an anchor)
            when, k = _when(v), int(k)
            if not when or _epoch(when) is None:
                continue
            _dated[(host, k)] = when
            anchors[k] = learned[k] = _epoch(when)
            if k in by_id:
                by_id[k]["date"] = when
        return bool(f.get("date"))

    working = True                       # (a forum that rests or shows no time is not asked again)
    for n, f in (rows[:1] + rows[-1:] if len(rows) > 1 else rows):
        if not f.get("date") and not covered(n) and not ask(n, f):
            working = False
            break
    while working and asked[0] < ASKS:
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
        lo = max((a for a in ns if a < n), default=None)
        hi = min((b for b in ns if b > n), default=None)
        if lo is None or hi is None:
            continue                            # never beyond the known times: the newest anchor's date for a picture posted since would be a lie
        f["date"] = _dated[(host, n)] = _iso(anchors[lo] + (anchors[hi] - anchors[lo]) * (n - lo) / (hi - lo))
    if learned:
        _learn(host, learned)
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


# ---- a forum without a media gallery: its attachment browser ------------------------------------------------

# The tile of an attachment browser links to the post the file sits in and shows a small copy; the file itself is
# `/attachments/<id>/`, which answers the raw original with no Content-Disposition, so the tile's alt text -- the
# uploader's own file name -- is what names the download. The tile shows no time; the post carries one above every
# file it holds. Attributes are read one by one, never in one fixed order: a theme puts `class` first, or `alt` before `src`.
# Nothing a page says is an address Sourcerer goes to: the post and the file are worked out from their ids, and only
# the small copy is taken from the page (_thumb).
_TILE = re.compile(r'<a\b([^>]*)>\s*<img\b([^>]*)>', re.I)
_TILE_POST = re.compile(r'href="[^"]*?\bposts/(\d+)/?"', re.I)
_TILE_FILE = re.compile(r'src="([^"]*?/attachments/\d+/(\d+)-[^"]+)"', re.I)
_TILE_ALT = re.compile(r'alt="([^"]*)"', re.I)
_POST_TIME = re.compile(r'id="post-(\d+)"|datetime="([^"]+)"', re.I)
_EXT = re.compile(r"\.(?=[a-z0-9]*[a-z])[a-z0-9]{2,5}$", re.I)       # "a.jpg", not "v2.5": the uploader's name, or a title with a dot
_VIDEO_EXT = re.compile(r"\.(mp4|webm|mov|m4v)$", re.I)             # the browser gives no content type
ATT_PAGE = 20                  # files per page handed to sync, as a media listing's PAGE
_gallery_route = {}            # host -> whether its media gallery exists (only what was settled is kept)
_public_hosts = {}             # host -> whether it is a public one (net.public_https), for the run


def _get(url):
    """A forum page at an address Sourcerer worked out itself (the gallery's front page, the attachment browser, a post): a 403 on
    it says nothing about the login (net.guess), so it is not counted as a refused one."""
    with net.guess():
        return net.get_text(url)


def _not_found(e):
    return e.response is not None and e.response.status_code == 404


def _tiles(text):
    """[(post id, small copy, attachment id, the uploader's file name)] of a browser page."""
    out = []
    for link, img in _TILE.findall(text):
        post, file = _TILE_POST.search(link), _TILE_FILE.search(img)
        if post and file:
            alt = _TILE_ALT.search(img)
            out.append((post.group(1), html.unescape(file.group(1)), file.group(2), html.unescape(alt.group(1)).strip() if alt else ""))
    return out


def _thumb(base, src):
    """A tile's small copy as an address: the forum's own, or a public host's (a CDN) -- a page never sends Sourcerer into this
    machine or its network. "" when it would."""
    url = urllib.parse.urljoin(base + "/", src)
    host = urllib.parse.urlsplit(url).hostname or ""
    if host != urllib.parse.urlsplit(base).hostname:
        if host not in _public_hosts:
            _public_hosts[host] = net.public_https(url)
        if not _public_hosts[host]:
            return ""
    return url


def _name(alt, att_id):
    """(name, filename) of a file by the name its uploader gave it. One with no extension (a title, "v2.5") names no file: it is
    the name's stem and the content type says the extension; with no name at all the id does."""
    ext = _EXT.search(alt)
    return ((alt[:ext.start()] if ext else alt) or att_id), (alt if ext else "")


def _att_url(base, member, page, indexphp):
    """A page of a member's attachment browser: `page-N` behind the friendly route, `&page=N` in the query for a
    forum that answers only `index.php?` -- the same second way pages() tries a media gallery."""
    if indexphp:
        return "%s/index.php?members/%s/attachment-browser/%s" % (base, member, ("&page=%d" % page) if page > 1 else "")
    return "%s/members/%s/attachment-browser/%s" % (base, member, ("page-%d" % page) if page > 1 else "")


def _uses_media_gallery(url):
    """Whether the forum has a Media Gallery at all: its front page, which a forum without the addon does not have (XenForo
    answers an unknown route with a 404). Asked once per forum -- for the forum, not for a member: a member the gallery does not
    know must never switch a gallery forum away -- and only a settled answer is kept: a forum that rests or cannot be reached
    raises, as any request does, and is asked again next time; any other answer (a refusal, an error page) means the gallery
    route exists and is left to gallery-dl as before."""
    host = _host(url)
    if host not in _gallery_route:
        p, _m = _parts(url)
        try:
            _get(urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), _m.group(1).rstrip("/") + "/index.php", "media/", "")))
            _gallery_route[host] = True
        except requests.HTTPError as e:
            _gallery_route[host] = not _not_found(e)
    return _gallery_route[host]


def _read_times(text):
    """{post id: time} of a thread or post page. XenForo prints each post twice -- an anchor and the message itself -- and the
    post's own time after the first; the datetime a page opens with dates the thread and belongs to no post, and the times
    that follow (an edit, a reaction) are not the post's."""
    times, cur, seen = {}, "", set()
    for m in _POST_TIME.finditer(text):
        if m.group(1):
            if m.group(1) not in seen:
                seen.add(m.group(1))
                cur = m.group(1)
        elif cur:
            times[cur], cur = _when(m.group(2)), ""
    return {k: v for k, v in times.items() if v}


def _post_times(post):
    """{post id: time} of what a post's address answers with: the thread page that holds it, so the post and its neighbours on that
    page -- one request dates them all. `post` is the item of _fill_dates: its `url` is the address."""
    return _read_times(_get(post["url"])[0])


def _attachment_pages(base, member, host, indexphp):
    """A member's attachments, page by page, post by post newest first -- the whole media of a forum that has no media gallery.
    A page of the browser is read for its tiles (the post a file sits in, its id, the small copy, the uploader's file name), the
    posts dated by _fill_dates -- post ids run forward like media ids, so their times are anchors of the forum's clock, kept like a
    media gallery's -- and the files handed on in batches of ATT_PAGE. The route is the one the link was pasted with (the
    friendly one, else `index.php?` for a forum that answers only that; the other is tried once on the first page). The browser
    prints no end-of-list marker, so the walk ends on a 404 or a page that brings nothing new (a page past the end answers with the last
    one) -- never on a short page: a tile that is no picture (a zip, a video) has other markup, so pages hold fewer of the tiles read
    here without being the last. Sync's own page cap bounds a forum that never ends."""
    from . import Media
    clock, page, seen, last, swapped = host + "/posts", 1, set(), None, False
    while True:
        try:
            text, _final = _get(_att_url(base, member, page, indexphp))
        except requests.HTTPError as e:
            if page == 1 and not swapped and e.response is not None and e.response.status_code in (403, 404):
                indexphp, swapped = not indexphp, True      # the guard answers the friendly route with a bare 403/404: its other way
                continue
            if _not_found(e):
                return                                      # no such page: the end (or a member with no attachments)
            _members_only(e, base)
            raise
        new = [tile for tile in _tiles(text) if tile[2] not in seen]
        if not new:
            try:
                _wall(text, host)                           # a guard's page has no tiles either: that is no end of the list
            except net.SlowDown:
                net.pause(base, 6 * 3600, "it let only a browser through")
                raise
            return
        seen.update(tile[2] for tile in new)
        route = "index.php?" if indexphp else ""
        posts = {}                                          # post id -> its item for _fill_dates, in the page's order
        for post_id, _thumb_src, _att, _alt in new:
            posts.setdefault(post_id, {"id": post_id, "url": "%s/%sposts/%s/" % (base, route, post_id), "date": ""})
        ids = [int(i) for i in posts]
        seq = ([last] if last is not None and last != ids[0] else []) + ids       # (a post may continue on the next page)
        _fill_dates(clock, list(posts.values()), all(a > b for a, b in zip(seq, seq[1:])), _post_times)
        last = ids[-1]
        for i in range(0, len(new), ATT_PAGE):
            batch = []
            for post_id, thumb_src, att_id, alt in new[i:i + ATT_PAGE]:
                url, (name, filename) = "%s/%sattachments/%s/" % (base, route, att_id), _name(alt, att_id)
                batch.append(Media(remote_key="xenforo:%s:a%s" % (host, att_id), url=url, large=url, name=name, filename=filename,
                                   post_url=posts[post_id]["url"], posted=_when(posts[post_id]["date"]),
                                   # the forum shows its files to members only: the gallery fetches even the small copies through
                                   # Sourcerer, with the login
                                   thumb=_thumb(base, thumb_src), preview_headers={}, video=bool(_VIDEO_EXT.search(alt))))
            yield batch
        page += 1


def pages(url):
    from . import LoginRequired, Media
    host = _host(url)
    net._stopped(url)
    p, m = _parts(url)
    # a forum without the Media Gallery addon: its member pages 404 and a member's media is its attachment browser
    if m.group(3).lower() in ("members", "media/users") and not _uses_media_gallery(url):
        yield from _attachment_pages("%s://%s%s" % (p.scheme, p.netloc.lower(), m.group(1).rstrip("/")), m.group(4), host, bool(m.group(2)))
        return
    if not _gdl.available():
        raise RuntimeError("Forums need gallery-dl, which did not install: Settings > Repair")
    listing = _gdl.items(url, None, _options(url), FIELDS, lock="xenforo:" + host, trace="xenforo")
    last = None                                    # the id of the last picture of the page before
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
        ids = [int(f["id"]) for f in batch if str(f["id"]).isdigit()]
        seq = ([last] if last is not None else []) + ids
        ordered = len(ids) == len(batch) and all(a > b for a, b in zip(seq, seq[1:]))      # newest first, by id, across the pages too
        last = ids[-1] if ids else last
        _fill_dates(host, batch, ordered)
        yield [Media(remote_key="xenforo:%s:%s" % (host, f["id"]), url=f["url"],
                     post_url=_post(f),
                     # the title is the file name's last resort and what a tile says (the forum's own name for the file
                     # comes with the download, and wins)
                     posted=_when(f.get("date")), name=_title(f),
                     # The forum shows its files to members only: the gallery fetches
                     # them through Sourcerer, with the login, and makes its own small copy.
                     large=f["url"], preview_headers={})
               for f in batch]
