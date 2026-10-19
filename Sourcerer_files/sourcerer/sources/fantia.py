"""Fantia (https://fantia.jp/fanclubs/<id>): a fanclub's posts, their pictures and files.

A visitor sees the free posts only; the login (a window under Manage Accounts: the session cookie) shows the
posts of the plans the user supports. Listing goes through gallery-dl (_gdl.py); the files are downloaded by
Sourcerer itself through net.py with the login's cookie. A post's own thumbnail is kept (Fantia artists
upload it as a picture of its own); a post's text is not.

Fantia gives a visitor a session cookie as well, so a cookie does not say who is logged in: the login window
and the account check read the page's `data-user-type` (a visitor's is "visitor") instead.
"""
import random
import re

from . import _gdl
from .. import accounts, net

KIND = "fantia"
LABEL = "Fantia"
HOME = "https://fantia.jp"
LOGIN = ("recommended", "Logged out, Fantia shows the free posts only; a supported plan's posts need the login.")
_URL = re.compile(r"^https?://(?:www\.)?fantia\.jp/fanclubs/(\d+)(?=[/?#]|$)", re.I)
OPTIONS = {"sleep-request": "2.0-4.0", "ratelimit": "abort", "text": False}
FIELDS = {"url": "{_url!j}", "post": "{post_id!j}", "num": "{num!j}", "file": "{file_id!j}", "key": "{filename!j}",
          "ext": "{extension!j}", "date": '"{date:%Y-%m-%dT%H:%M:%SZ}"', "fanclub": "{fanclub_id!j}",
          "post_url": "{post_url!j}", "title": "{post_title!j}"}
VISITOR = re.compile(r'<body[^>]*\bdata-user-type="([^"]*)"')


def match(url):
    return bool(_URL.match(url.strip()))


def _id(url):
    return _URL.match(url.strip()).group(1)


def account_key(url):
    return "fantia"


def normalize(url):
    return "%s/fanclubs/%s" % (HOME, _id(url))


def _options():
    return dict(OPTIONS, cookies=accounts.jar("fantia", fresh=True))


def still_logged_in(key):
    """Whether the front page, asked with the login, greets a member (the cookie alone proves nothing)."""
    text, _final = net.get_text(HOME + "/")
    m = VISITOR.search(text)
    return bool(m) and m.group(1) not in ("", "visitor")


def profile(url):
    fanclub = _id(url)
    club = net.get_json("%s/api/v1/fanclubs/%s" % (HOME, fanclub),
                        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})["fanclub"]
    return {"name": club.get("creator_name") or club.get("fanclub_name_or_creator_name") or "Fanclub " + fanclub,
            "handle": "fantia.jp/fanclubs/" + fanclub, "avatar": (club.get("icon") or {}).get("main") or ""}


def _run(fn, *args):
    try:
        return fn(*args)
    except _gdl.Failed as e:
        if e.slow or "429" in str(e):
            net.pause(HOME, random.uniform(1, 2) * 3600, "Fantia asked Sourcerer to slow down")
            raise net.SlowDown("Fantia asked Sourcerer to slow down; it rests for a while") from e
        raise


def pages(url):
    from . import Media
    if not _gdl.available():
        raise RuntimeError("Fantia needs gallery-dl, which did not install: Settings > Repair")
    net._stopped(HOME)
    listing = _gdl.items(normalize(url), "fantia", _options(), FIELDS)
    while True:
        net._stopped(HOME)
        try:
            batch = _run(next, listing)
        except StopIteration:
            return
        if accounts.logged_in("fantia"):
            net.spend(HOME, len(batch))
        yield [Media(remote_key="fantia:%s:%s" % (f["post"], f["file"]), url=f["url"],
                     post_url=f.get("post_url") or "%s/posts/%s" % (HOME, f["post"]),
                     posted=f.get("date") or "", name="%s_%s" % (f["post"], f["file"]),
                     # "album_image" is a redirect to the picture, not a name: the server's own name is used.
                     filename="%s.%s" % (f["key"], f["ext"]) if f.get("key") and f.get("ext") else "",
                     headers={"Referer": HOME + "/"}, large=f["url"], preview_headers={"Referer": HOME + "/"})
               for f in batch if f.get("url") and f.get("file") is not None and not str(f["url"]).startswith("text:")]
