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
# (A member's attachment browser, `.../attachment-browser`, is the same member: the suffix is matched and dropped.)
_PATH = re.compile(r"^(.*?)/(index\.php\?)?(media/users|members|media/albums|threads)/([^/?#]+?)(?:/attachment-browser)?(?=[/?#]|$)", re.I)
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
    # the address (`members/90414`) is known by the member route alone -- its follow list names members so.
    return bool(m and (re.search(r"\.\d+$", m.group(4)) or (m.group(3).lower() == "members" and m.group(4).isdigit())))


def normalize(url):
    """A member's media gallery for a member's link -- and for its attachment browser, which some
    forums put in front of it (_attachment_pages); albums and threads as they are."""
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
    picture of it). {} when the page says nothing. A file of an attachment browser is known by the post it sits in:
    that post's own time is what the viewer should show, not the thread's opening the page's JSON-LD dates."""
    post = getattr(media, "post_url", "") or (media if isinstance(media, str) else "")
    found = re.search(r"/posts/(\d+)", post)
    return _page_info(post, found.group(1) if found else "")


def _page_info(post_url, post_id=""):
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
    # (+0000 is not an ISO offset to every parser)
    posted = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", main.get("dateCreated") or "")
    if post_id:
        # a file of an attachment browser: its post address answers with the thread page that holds it, whose JSON-LD
        # dates the *thread* -- the time printed under that post is the one to show. (Never a guess for a media item:
        # _fill_dates keeps what it reads here as an anchor of the forum's clock.)
        posted = _read_times(text)[0].get(post_id) or posted
    out = {"title": html.unescape(main.get("name") or ""), "description": html.unescape(main.get("description") or ""),
           "posted": posted, "author": html.unescape((author.get("name") if isinstance(author, dict) else author) or ""),
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

# what a forum without a media gallery says about when: a post and the files it carries, kept from the pages that were read
_post_time = {}                  # (host, post id) -> the time that post was made
_att_time = {}                   # (host, attachment id) -> the time its file was attached
MAX_POST_TIME = 4000             # post pages remembered: more are dropped from the front
_page_reads = {}                 # post address -> (what one read of its page gave: {post id: time}, {attachment id: time})


def _fill_dates(host, batch, ordered=False):
    """Dates for the pictures of a batch whose tile showed none (the list page of many forums shows no time at all). A picture's page has
    the exact time -- one request each, which a gallery of hundreds cannot ask for. A forum numbers its media as it goes, so the id is a
    clock that only runs forward: the time of the batch's lowest and highest id is read from their own pages, then of the middle one of the
    widest gap between two known times, until the gaps are under two days or ASKS pages were read; the pictures between are placed by their
    id, which cannot be wrong by more than the gap they sit in. Done only where somebody waits (an artist's gallery: net.waiting) and never
    for a sync, nor when the forum is the gallery's only source *and* lists its pictures newest first by id (`ordered`, checked page by
    page in pages(): the ids only run forward, so the forum's own order is the order of their dates -- the first page used to wait for up to
    seven page requests; the viewer still shows the exact time when a picture opens). A forum that lists in another order is dated as ever; whatever is known is kept (_dated) and the next listing asks for nothing it knows. Any trouble -- the forum rests, wants a
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
        anchors[n] = learned[n] = _epoch(when)
        return True

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
# uploader's own file name -- is what names the download. The tile shows no time; the post it links to carries one
# above every file it holds, which is where _post_dates reads them from. Attributes are read one by one, never in
# one fixed order: a theme puts `class` first, or `alt` before `src`.
_TILE = re.compile(r'<a\b([^>]*)>\s*<img\b([^>]*)>', re.I)
_TILE_POST = re.compile(r'href="([^"]*?\bposts/(\d+)/?)"', re.I)
_TILE_FILE = re.compile(r'src="([^"]*?/attachments/\d+/(\d+)-[^"]+)"', re.I)
_TILE_ALT = re.compile(r'alt="([^"]*)"', re.I)
ATT_PAGE = 20                  # files per page handed to sync, as a media listing's PAGE
MAX_ATT_PAGES = 200            # 20 000 files: a browser that never ends is the forum's fault
# the browser gives no content type, so a file is known to be a video by the name its uploader gave it
_VIDEO_EXT = re.compile(r"\.(mp4|webm|mov|m4v)$", re.I)
_gallery_route = {}            # host -> whether its media gallery answers (only what was settled is kept)

_DT_OR_ATT = re.compile(r'id="post-(\d+)"|datetime="([^"]+)"|id="attachment-(\d+)"', re.I)


def _tiles(text):
    """[(post address as the page wrote it, post id, small copy, attachment id, the uploader's file name)] of a browser page."""
    out = []
    for link, img in _TILE.findall(text):
        post, file = _TILE_POST.search(link), _TILE_FILE.search(img)
        if post and file:
            alt = _TILE_ALT.search(img)
            out.append((html.unescape(post.group(1)), post.group(2), html.unescape(file.group(1)), file.group(2),
                        html.unescape(alt.group(1)).strip() if alt else ""))
    return out


def _site_url(base, href):
    """A link of a forum page as an address. Root-relative hrefs resolve against the origin, not against a base that
    already carries the forum's folder; a page that left the folder out of its links gets it back in front."""
    parts = urllib.parse.urlsplit(base)
    if not href.startswith("/"):
        return urllib.parse.urljoin(base + "/", href)
    folder = parts.path.rstrip("/")
    if folder and not href.lower().startswith(folder.lower() + "/"):
        href = folder + href
    return "%s://%s%s" % (parts.scheme, parts.netloc, href)


def _att_url(base, member, page, indexphp):
    """A page of a member's attachment browser: `page-N` behind the friendly route, `&page=N` in the query for a
    forum that answers only `index.php?` -- the same second way pages() tries a media gallery."""
    if indexphp:
        return "%s/index.php?members/%s/attachment-browser/%s" % (
            base, member, ("&page=%d" % page) if page > 1 else "")
    return "%s/members/%s/attachment-browser/%s" % (
        base, member, ("page-%d" % page) if page > 1 else "")


def _not_found(e):
    return e.response is not None and e.response.status_code == 404


def _uses_media_gallery(url):
    """Whether this member's media is in a Media Gallery -- false where the forum has none. The probe is the very
    address gallery-dl would be pointed at, so a forum that has the gallery costs one request, once. A 404 there is
    this member's alone until the gallery's front page 404s too: only then is "no gallery" kept for the forum (a
    gallery forum is never switched away by one member it does not know). A forum that cannot be reached, or rests,
    is left to gallery-dl as before and asked again next time."""
    host = _host(url)
    if host in _gallery_route:
        return _gallery_route[host]
    p, m = _parts(url)
    base = "%s://%s%s" % (p.scheme, p.netloc.lower(), m.group(1).rstrip("/"))
    try:
        net.get_text("%s/index.php?%s/%s" % (base, m.group(3).lower(), m.group(4)))
        _gallery_route[host] = True
        return True
    except requests.HTTPError as e:
        if not _not_found(e):
            return True
    except Exception:
        return True
    try:
        net.get_text(base + "/index.php?media/")
    except requests.HTTPError as e:
        if _not_found(e):
            _gallery_route[host] = False
    except Exception:
        pass
    return False


def _read_times(text):
    """What a thread or post page says about when: ({post id: time}, {attachment id: time}, the page's leading
    datetime, the time of the last post it shows). XenForo prints each post twice -- an anchor and the message
    itself -- and the post's time between the two, and a page's leading datetime belongs to no post of it (it
    dates the thread); the files of a post come after its time and belong to it."""
    posts, atts, lead, last, cur, when, pending, seen = {}, {}, "", "", "", "", False, set()
    for m in _DT_OR_ATT.finditer(text):
        if m.group(1):
            if m.group(1) not in seen:
                cur, pending, when = m.group(1), True, ""
            seen.add(m.group(1))
        elif m.group(2):
            if pending:
                posts[cur] = last = when = _when(m.group(2))
                pending = False
            elif not cur:
                lead = lead or _when(m.group(2))
        elif cur and when:
            atts.setdefault(m.group(3), when)
    return posts, atts, lead, last


def _post_dates(post_url, post_id):
    """The time of one post, of every attachment it carries and of every other post on the page it answers with:
    (the post's time or "", {attachment id: time}, {post id: time}). XenForo prints each file under its post's
    `<time>`, so the first datetime that follows an `id="post-<id>"` is that post's own and the files that come
    after it belong to it -- the attachment browser's tile shows none. A post address answers by redirecting to the
    thread page that holds it, which carries the other posts of that page too: their times come along for nothing,
    and so do their files. A page is read once (a post it does not show, or a page with no time, would otherwise be
    asked for again at every listing)."""
    key = post_url.split("#")[0]
    hit = _page_reads.get(key)
    if hit is None:
        try:
            text, _final = net.get_text(post_url)
        except requests.HTTPError as e:
            _members_only(e, post_url)
            raise
        posts, atts, _lead, _last = _read_times(text)
        if len(_page_reads) > MAX_POST_TIME:
            for k in list(_page_reads)[:MAX_POST_TIME // 2]:
                _page_reads.pop(k, None)
        hit = _page_reads[key] = (posts, atts)
    return hit[0].get(post_id, ""), hit[1], hit[0]


def _fill_att_dates(host, batch, ordered=False):
    """Dates for the files of a page of the attachment browser, whose tiles show none. An attachment id is *not*
    a clock here the way a media id is: a forum numbers files as they are uploaded, and a post made later can
    carry files made earlier -- the browser's own order, post by post, is what runs forward in time. So the page
    is taken as its posts (a post's files were all attached at the time of that post, and one read of a post's page
    dates the posts around it on the same thread page, which is why the asks go to posts and not to files): the
    first and the last post are read, then the middle post of the widest gap between two known times, until the
    gaps are under two days or ASKS pages were read; the posts between are placed by their place in the listing,
    which cannot be off by more than the gap they sit in. Asked only where somebody waits (an artist's gallery:
    net.waiting) and never for a sync, which leaves them undated as a media listing does -- nor when the forum is
    the gallery's only source *and* the browser lists post by post newest first (`ordered`): then the browser's
    order is the order of the dates. Whatever is known is kept (_post_time, _att_time) and the next listing asks
    for nothing it knows. Any trouble -- the forum rests, wants a login, a post it does not show -- leaves the
    files as they are (undated, or placed between what was read)."""
    groups = []                                  # [(post id, post address, [files])]: the posts of the page in its order
    for f in batch:
        key = str(f.get("post_id") or "")
        if groups and groups[-1][0] == key:
            groups[-1][2].append(f)
        else:
            groups.append((key, f["post"], [f]))
    for key, _post_address, files in groups:
        hit = _post_time.get((host, key))
        if hit:
            for f in files:
                f["date"] = _att_time[(host, str(f.get("id")))] = hit
    if all(f.get("date") for f in batch) or not net.waiting() or (net.sole() and ordered):
        return
    times = [_post_time.get((host, key)) or "" for key, _, _ in groups]
    times = [t if _epoch(t) is not None else "" for t in times]
    asked = [0]

    def ask(i):
        """Read the page of the i-th post: its time and that of every other post the page carries come along, and
        with them the files of all of those. False when the post is not on what the address answered (a thread
        that has moved on) or shows no time -- then nothing was learned about it."""
        key, address, files = groups[i]
        try:
            own, got, page = _post_dates(address, key)
        except Exception as e:
            log.info("%s: no date for the post of attachment %s: %s", host, files[0].get("id"), net.reason(e))
            return False
        asked[0] += 1
        for pid, iso in page.items():
            if iso and _epoch(iso) is not None:
                _post_time[(host, pid)] = iso
        for att, iso in got.items():
            if _epoch(iso) is not None:
                _att_time[(host, att)] = iso
        if not own or _epoch(own) is None:
            return False
        times[i] = own
        for f in files:
            f["date"] = _att_time[(host, str(f.get("id")))] = own
        return True

    def bracket(i):
        """The nearest posts with a known time before and after post i, or None where one side is missing -- nothing
        to place it between."""
        lo = max((j for j in range(i) if times[j]), default=None)
        hi = min((j for j in range(i + 1, len(times)) if times[j]), default=None)
        return None if lo is None or hi is None else (lo, hi)

    def span(b):
        return abs(_epoch(times[b[1]]) - _epoch(times[b[0]]))

    for i in (0, len(groups) - 1):
        if not times[i] and not (bracket(i) and span(bracket(i)) <= CLOSE) and not ask(i):
            break
    while asked[0] < ASKS:
        gaps = {}
        for i in range(len(groups)):
            b = None if times[i] else bracket(i)
            if b:
                gaps.setdefault(b, []).append(i)
        if not gaps:
            break
        b = max(gaps, key=span)
        if span(b) <= CLOSE or not ask(gaps[b][len(gaps[b]) // 2]):
            break
    for i, (_key, _address, files) in enumerate(groups):
        b = None if times[i] else bracket(i)
        if not b:
            continue                         # never beyond the known times, as with a media listing
        lo, hi = b
        when = _epoch(times[lo]) + (_epoch(times[hi]) - _epoch(times[lo])) * (i - lo) / (hi - lo)
        for f in files:
            f["date"] = _att_time[(host, str(f.get("id")))] = _iso(when)
    if len(_post_time) > MAX_DATED or len(_att_time) > MAX_DATED:
        _post_time.clear()
        _att_time.clear()


def _listed_by_time(rows):
    """Whether an attachment browser's own order is the order of the files' dates: the browser lists whole posts
    newest first and keeps a post's files together, and post ids run forward like media ids do -- so the newest
    file of the newest post heads the page. Within a post the files may come in any order, which matters to nothing:
    they were all attached at the time of that post. True lets a sync trust that order instead of asking post pages
    for times, as pages() does for a media gallery that lists its pictures by id."""
    posts = []
    for f in rows:
        if not posts or posts[-1] != f["post_id"]:
            if f["post_id"] in posts:
                return False                        # a post split across the page: the order is not by post
            posts.append(f["post_id"])
    return all(int(a) > int(b) for a, b in zip(posts, posts[1:]))


def _attachment_pages(base, member, host):
    """A member's attachments, page by page, post by post newest first -- the whole media of a forum that has no
    media gallery. Each page of the browser is read for its tiles (the post a file sits in, its id, the small copy,
    the uploader's file name), dated by _fill_att_dates, then handed on in batches of ATT_PAGE as Media. The route
    is settled on the first page (the friendly one, else `index.php?` for a forum that answers only that) and kept.
    The browser prints no end-of-list marker, so the walk ends on a page the forum does not know (a 404) or one that
    brings nothing new (a page past the end answers with the last one) -- never on a short page: a tile that is no
    picture (a zip, a video) has other markup, and the pages hold fewer of the tiles read here without being the last."""
    from . import Media
    indexphp, page, seen = False, 1, set()
    while page <= MAX_ATT_PAGES:
        try:
            text, _final = net.get_text(_att_url(base, member, page, indexphp))
        except requests.HTTPError as e:
            if page == 1 and not indexphp and _not_found(e):
                indexphp = True                          # the guard answers the friendly route with a 404: its other way
                continue
            if _not_found(e):
                return                                   # no such page: the end (or a member with no attachments)
            _members_only(e, base)
            raise
        new = []
        for href, post_id, thumb, att_id, alt in _tiles(text):
            if att_id in seen:
                continue
            seen.add(att_id)
            new.append({"post": _site_url(base, href), "post_id": post_id, "id": att_id, "thumb": thumb,
                        "url": "%s/%sattachments/%s/" % (base, "index.php?" if indexphp else "", att_id),
                        "name": alt or "%s.jpg" % att_id, "date": _att_time.get((host, att_id), "")})
        if not new:
            if page == 1:
                _wall(text, host)                        # a bot check answers 200 with no tiles: not "no attachments"
            return
        _fill_att_dates(host, new, ordered=_listed_by_time(new))
        for i in range(0, len(new), ATT_PAGE):
            yield [Media(remote_key="xenforo:%s:a%s" % (host, f["id"]), url=f["url"],
                         post_url=f["post"], posted=f.get("date") or "",
                         name=f["name"].rsplit(".", 1)[0] or f["id"],
                         filename=f["name"] if "." in f["name"] else "",
                         # the forum shows its files to members only: the gallery fetches even the small copies through
                         # Sourcerer, with the login -- and an address of the forum's own, not a root-relative link of a page
                         thumb=_site_url(base, f["thumb"]), preview_headers={},
                         video=bool(_VIDEO_EXT.search(f["name"])), large=f["url"])
                   for f in new[i:i + ATT_PAGE]]
        page += 1


def pages(url):
    from . import LoginRequired, Media
    host = _host(url)
    net._stopped(url)
    p, m = _parts(url)
    # a forum without the Media Gallery addon: its member pages 404 and a member's media is its attachment browser
    if m.group(3).lower() in ("members", "media/users") and not _uses_media_gallery(url):
        yield from _attachment_pages("%s://%s%s" % (p.scheme, p.netloc.lower(), m.group(1).rstrip("/")), m.group(4), host)
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
