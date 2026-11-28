"""PoiPiku (https://poipiku.com/<id>/): an artist's posts and their pictures.

A visitor sees the 640 px copies the pages show (the original answers 403); the login (a window under Manage Accounts:
the POIPIKU_LK cookie, empty for a visitor) gives the originals and the posts shown to members. Listing goes through
gallery-dl (_gdl.py); the files are downloaded by Sourcerer itself through net.py with the login's cookie.

The site's robots.txt asks for a crawl delay of 5 seconds: a sync spaces gallery-dl's pages by it (a gallery somebody waits for goes faster). A post has no date on
its page, so `posted` stays empty and the order of the listing (newest first) dates the saved files.
"""
import html
import logging
import random
import re
import urllib.parse

from . import _gdl, kinds
from .. import accounts, net

log = logging.getLogger(__name__)
KIND = "poipiku"
LABEL = "PoiPiku"
HOME = "https://poipiku.com"
LOGIN = ("recommended", "Logged out, PoiPiku shows 640 px copies only; the original pictures and the posts for members need the login.")
# /<id>/, a post (/<id>/<post>.html) or the list page's own address (IllustListPcV.jsp?PG=0&ID=<id>).
_URL = re.compile(r"^https?://(?:www\.)?poipiku\.com/(?:IllustListPcV\.jsp\?(?:[^#]*&)?ID=(\d+)(?=&|#|$)|(\d+)(?=[/?#]|$))", re.I)
OPTIONS = {"sleep-request": "5.0-7.0", "ratelimit": "abort"}        # robots.txt: Crawl-delay 5, kept by every sync
OPEN_SLEEP = "2.5-4.0"      # ... while somebody waits for the page (an artist's gallery): a person clicking through posts. One post is one page: 5-7 s made the first screen two minutes
FIELDS = {"url": "{_url!j}", "post": "{post_id!j}", "num": "{num!j}", "user": "{user_id!j}", "key": "{filename!j}", "ext": "{extension!j}"}
# Only a file on the site's own picture hosts: <host>/<user, nine digits>/<name> (the post's lock and warning icons are on /img/ and /assets/).
# A member's original is a signed CloudFront link (<name>?Expires=...&Signature=...&Key-Pair-Id=...): without the query every logged-in file was dropped.
_FILE = re.compile(r"^https://(?:cdn|img)\.poipiku\.com/(?:user_img\d+/)?\d{9}/[^/?#]+(?:\?[^#\s]*)?$")
_COPY = re.compile(r"^(.+?)\.(\w+)_(?:120|360|640)\.jpg$")            # a rendition: <name>.<ext>_640.jpg, the original is <name>.<ext>


def match(url):
    return bool(_URL.match(url.strip()))


def _id(url):
    m = _URL.match(url.strip())
    return m.group(1) or m.group(2)


def account_key(url):
    return "poipiku"


def normalize(url):
    return "%s/%s/" % (HOME, _id(url))


def profile(url):
    uid = _id(url)
    text, _final = net.get_text(HOME + "/IllustListPcV.jsp", params={"PG": 0, "ID": uid, "KWD": ""})
    name = re.search(r'class="UserInfoUserName">(?:<a[^>]*>)?([^<]+)', text)
    avatar = re.search(r'src="(https://cdn\.poipiku\.com/\d{9}/profile_[^"]+)"', text)
    return {"name": html.unescape(name.group(1)).strip() if name else "PoiPiku " + uid,
            "handle": "poipiku.com/" + uid, "avatar": avatar.group(1) if avatar else ""}


# ---- the accounts a login follows ---------------------------------------------------------------------------------------------------
# PoiPiku has no list of them: "Following" (MyHomePcV.jsp, the tab "quiet follow") is the FEED of their posts, newest first, in the same cards the public
# pages use (<a class="IllustUser" href="/<id>/"><img class="IllustUserThumb" ...><h2 class="IllustUserName">), paged by PG (0-based, a PageBar with a link to the
# next one). So the follows are the authors found in it: whoever posted lately -- an account that follows and has not posted for longer than the feed reaches is
# missing until it posts. Written from the public feeds' markup (NewArrivalPcV.jsp), not seen with a real login.
# A feed is ordered by when the authors POSTED, not by when one followed them: a new follow's last post can be on any page, so the walk never stops at a page of known
# accounts (follows._look: WHOLE_FEED) and there is no minimum between two looks (no FOLLOWS_HOURS: "Refresh all" right after following somebody must find them). A look is
# up to MAX_FEED_PAGES requests, 5 s apart (robots.txt): minutes, in the background, inside the day's budget.
WHOLE_FEED = True
MAX_FEED_PAGES = 40
_USER = re.compile(r'<a class="IllustUser" href="/(\d+)/">(.*?)</a>', re.S)            # the grid's card (the public pages)
_ITEM = re.compile(r'<div class="IllustItemUser">(.*?)</h2>', re.S)                    # the list's post header (the Following feed: a post, its emoji keyboard, ...)
_UID = re.compile(r'href="/(\d+)/"')
_NAME = re.compile(r'class="IllustUserName">([^<]*)<|class="IllustItemUserName"><a[^>]*>([^<]*)<')
_ALT = re.compile(r'class="IllustUserThumb"[^>]*\balt="([^"]*)"')
_AVATAR = re.compile(r'(?:src="|url\([\'"]?)(https://cdn\.poipiku\.com/\d{9}/profile_[^"\')]+)')    # (the default picture is no avatar: the initials show)
_BAR = re.compile(r'<nav class="PageBar">(.*?)</nav>', re.S)


def _authors(text):
    """The accounts of one feed page, once each, in the order they come: [{"url", "name", "avatar"}]. Two layouts: the grid's cards and the list's post headers."""
    found = list(_USER.findall(text))
    for inner in _ITEM.findall(text):
        uid = _UID.search(inner)
        if uid:
            found.append((uid.group(1), inner))
    out, seen = [], set()
    for uid, inner in found:
        if uid in seen:
            continue
        seen.add(uid)
        name = _NAME.search(inner)
        name = (name.group(1) or name.group(2)) if name else (_ALT.search(inner) or [None, ""])[1]
        avatar = _AVATAR.search(inner)
        out.append({"url": "%s/%s/" % (HOME, uid), "name": html.unescape(name or "").strip(), "avatar": avatar.group(1) if avatar else ""})
    return out


def following(key):
    """(list name, pages) of the accounts in the login's Following feed. A feed that shows the login page is an expired login (it says so);
    one with no post at all is a login that follows nobody, or nobody who posted: an empty list, no error."""
    def pages():
        seen, last = set(), 0
        for page in range(MAX_FEED_PAGES):
            net._stopped(HOME)
            text, _final = net.get_text(HOME + "/MyHomePcV.jsp", params={"PG": page})
            fresh = [a for a in _authors(text) if a["url"] not in seen]
            if not fresh and page == 0:                  # (nothing is "seen" yet: no author at all)
                if "LoginButton" in text or "LoginFormEmailPcV" in text:
                    raise RuntimeError("PoiPiku showed its login page: log in again in Manage Accounts")
                log.warning("PoiPiku: the Following feed shows no post card (%d bytes; IllustThumb x%d, IllustUser x%d, IllustItemUser x%d, PageBar x%d) -- the markup differs from what is known",
                            len(text), text.count("IllustThumb"), text.count("IllustUser"), text.count("IllustItemUser"), text.count("PageBar"))
            seen.update(a["url"] for a in fresh)
            last = page
            if fresh:
                yield fresh
            bar = _BAR.search(text)
            if not bar or not re.search(r'href="[^"]*[?&]PG=%d(?:&|")' % (page + 1), bar.group(1)):
                break                  # no link to the next page: this was the last (a page past the end answers with the last one, so never walk on a guess)
        log.info("PoiPiku: %d accounts in the Following feed (%d pages)", len(seen), last + 1)
    yield "", pages()


def _run(fn, *args):
    try:
        return fn(*args)
    except _gdl.Failed as e:
        if e.slow or "429" in str(e):
            net.pause(HOME, random.uniform(1, 2) * 3600, "PoiPiku asked Sourcerer to slow down")
            raise net.SlowDown("PoiPiku asked Sourcerer to slow down; it rests for a while") from e
        raise


def _media(f):
    """The Media of one listed file, or None for a file that is none of the artist's (an icon, a lock)."""
    from . import Media
    url = f.get("url") or ""
    if not _FILE.match(url) or f.get("num") is None:
        return None
    base = url.partition("?")[0]             # the small rendition is public and unsigned, so it is made from the address without the signature
    name = urllib.parse.unquote(base.rsplit("/", 1)[-1])
    m = _COPY.match(name)
    if m:                                    # a visitor's 640 px copy: the picture is under its own name, without the rendition's
        base = base[:base.rfind("/") + 1] + "%s.%s" % (m.group(1), m.group(2))
        name = "%s_640.jpg" % m.group(1)
    post = f.get("post")
    return Media(remote_key="poipiku:%s:%s" % (post, f["num"]), url=url,
                 post_url="%s/%s/%s.html" % (HOME, f.get("user") or "", post), posted="",
                 name="%s_%s" % (post, f["num"]), filename=name, headers={"Referer": HOME + "/"},
                 thumb=base + "_360.jpg", large=url, preview_headers={"Referer": HOME + "/"}, **kinds.typed(name))


def pages(url):
    if not _gdl.available():
        raise RuntimeError("PoiPiku needs gallery-dl, which did not install: Settings > Repair")
    net._stopped(HOME)
    options = dict(OPTIONS, cookies=accounts.jar("poipiku", fresh=True))
    if net.waiting():
        options["sleep-request"] = OPEN_SLEEP
    # A logged-in read counts its requests against the day's budget (gallery-dl's log, _gdl.items(site=)); a visitor's is nobody's.
    listing = _gdl.items(normalize(url), "poipiku", options, FIELDS, site=HOME if accounts.logged_in("poipiku") else None)
    while True:
        net._stopped(HOME)
        try:
            batch = _run(next, listing)
        except StopIteration:
            return
        yield [m for m in map(_media, batch) if m]
