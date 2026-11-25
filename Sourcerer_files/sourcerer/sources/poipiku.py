"""PoiPiku (https://poipiku.com/<id>/): an artist's posts and their pictures.

A visitor sees the 640 px copies the pages show (the original answers 403); the login (a window under Manage Accounts:
the POIPIKU_LK cookie, empty for a visitor) gives the originals and the posts shown to members. Listing goes through
gallery-dl (_gdl.py); the files are downloaded by Sourcerer itself through net.py with the login's cookie.

The site's robots.txt asks for a crawl delay of 5 seconds: a sync spaces gallery-dl's pages by it (a gallery somebody waits for goes faster). A post has no date on
its page, so `posted` stays empty and the order of the listing (newest first) dates the saved files.
"""
import html
import random
import re
import urllib.parse

from . import _gdl, kinds
from .. import accounts, net

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
_FILE = re.compile(r"^https://(?:cdn|img)\.poipiku\.com/(?:user_img\d+/)?\d{9}/[^/?#]+$")
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
    base, name = url, urllib.parse.unquote(url.rsplit("/", 1)[-1])
    m = _COPY.match(name)
    if m:                                    # a visitor's 640 px copy: the picture is under its own name, without the rendition's
        base = url[:url.rfind("/") + 1] + "%s.%s" % (m.group(1), m.group(2))
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
