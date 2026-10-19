"""Fanbox (pixiv's patron site): https://<creator>.fanbox.cc or https://www.fanbox.cc/@<creator>.

Needs the login (FANBOXSESSID, a window under Manage Accounts: it goes through pixiv's login page): Fanbox
answers a visitor's request for a post with a 403. Listing goes through gallery-dl (_gdl.py), which
follows Fanbox's API; the files -- downloads.fanbox.cc, which wants a Referer and the login's cookie -- are
downloaded by Sourcerer itself through net.py. A post's cover is left out (a cut of one of its pictures);
embedded videos of other sites (YouTube...) are no files of Fanbox's.

A login is what gets banned: the listing is paced like X's (a random gap, a rate limit ends it and the site
rests), and the day's files count against net.BUDGETS["fanbox"].
"""
import random
import re

import requests

from . import _gdl
from .. import accounts, net

KIND = "fanbox"
LABEL = "Fanbox"
HOME = "https://www.fanbox.cc"
FOLLOWS_HOURS = 11        # follows.py reads the list of followed accounts at most this often
LOGIN = ("required", "Fanbox shows its posts only to logged-in accounts.")
_RESERVED = {"www", "api", "downloads", "image", "assets", "help", "official", "blog", "fanbox", "payment"}
_URL = re.compile(r"^https?://(?:(?!www\.)([\w-]+)\.fanbox\.cc|(?:www\.)?fanbox\.cc/@([\w-]+))(?=[/?#]|$)", re.I)
OPTIONS = {"sleep-request": "2.0-4.0", "ratelimit": "abort", "embeds": False}
HEADERS = {"Referer": HOME + "/"}
FIELDS = {"url": "{_url!j}", "post": "{id!j}", "num": "{num!j}", "file": "{fileId!j}", "key": "{filename!j}",
          "ext": "{extension!j}", "date": '"{date:%Y-%m-%dT%H:%M:%SZ}"', "user": "{creatorId!j}",
          "cover": "{isCoverImage!j}", "title": "{title!j}", "w": "{width!j}", "h": "{height!j}"}


def _creator(url):
    m = _URL.match(url.strip())
    name = (m.group(1) or m.group(2)) if m else None
    return name if name and name.lower() not in _RESERVED else None


def match(url):
    return _creator(url) is not None


def account_key(url):
    return "fanbox"


def normalize(url):
    return "https://%s.fanbox.cc" % _creator(url)


def _options():
    return dict(OPTIONS, cookies=accounts.jar("fanbox", fresh=True))


def still_logged_in(key):
    """The list of creators the account follows: a visitor is answered with a 400 (or 401/403)."""
    try:
        net.get_json("https://api.fanbox.cc/creator.listFollowing", headers={"Origin": HOME})
        return True
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (400, 401, 403):
            return False
        raise


def following(key):
    """(list name, pages) of the creators the login follows and supports: [{"url", "name", "avatar"}]. The lists are the
    account's own (a visitor is answered with a 400)."""
    def pages():
        seen = set()
        for endpoint, name in (("creator.listFollowing", "following"), ("plan.listSupporting", "supporting")):
            try:
                body = net.get_json("https://api.fanbox.cc/" + endpoint, headers={"Origin": HOME}).get("body") or []
            except Exception:
                if name == "supporting":         # the second list is a bonus: its shape is the site's to change
                    break
                raise
            out = []
            for item in body if isinstance(body, list) else []:
                creator = item.get("creatorId") or ""
                user = item.get("user") or {}
                if creator and creator.lower() not in seen and _creator("https://%s.fanbox.cc" % creator):
                    seen.add(creator.lower())
                    out.append({"url": "https://%s.fanbox.cc" % creator, "name": user.get("name") or creator,
                                "avatar": user.get("iconUrl") or "", "avatar_headers": HEADERS})
            yield out
    yield "", pages()


def profile(url):
    from . import LoginRequired
    name = _creator(url)
    try:
        body = net.get_json("https://api.fanbox.cc/creator.get", {"creatorId": name}, headers={"Origin": HOME})["body"]
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            raise LoginRequired("Fanbox: log in") from e
        raise
    user = body.get("user") or {}
    return {"name": user.get("name") or name, "handle": "%s.fanbox.cc" % name, "avatar": user.get("iconUrl") or ""}


def _run(fn, *args):
    from . import LoginRequired
    try:
        return fn(*args)
    except _gdl.Failed as e:
        if e.slow or "429" in str(e):
            net.pause(HOME, random.uniform(1, 2) * 3600, "Fanbox asked Sourcerer to slow down")
            raise net.SlowDown("Fanbox asked Sourcerer to slow down; it rests for a while") from e
        if e.auth or "403" in str(e):
            raise LoginRequired("Fanbox: log in" + (" again" if accounts.logged_in("fanbox") else "")) from e
        raise


def pages(url):
    from . import LoginRequired, Media
    if not _gdl.available():
        raise RuntimeError("Fanbox needs gallery-dl, which did not install: Settings > Repair")
    if not accounts.logged_in("fanbox"):
        raise LoginRequired("Fanbox shows its posts only to a logged-in account")
    creator = _creator(url)
    net._stopped(HOME)
    listing = _gdl.items(normalize(url), "fanbox", _options(), FIELDS)
    while True:
        net._stopped(HOME)                 # spent or refused meanwhile: gallery-dl cannot see a pause
        try:
            batch = _run(next, listing)
        except StopIteration:
            return
        net.spend(HOME, len(batch))
        found = [f for f in batch if f.get("url") and not f.get("cover") and "fanbox" in f["url"]]
        yield [Media(remote_key="fanbox:%s:%s" % (f["post"], f.get("file") or "n%s" % f["num"]), url=f["url"],
                     post_url="%s/@%s/posts/%s" % (HOME, f.get("user") or creator, f["post"]),
                     posted=f.get("date") or "", name="%s_%s" % (f["post"], f["num"]),
                     filename="%s.%s" % (f["key"], f["ext"]) if f.get("key") and f.get("ext") else "",
                     headers=HEADERS, large=f["url"], width=f.get("w") or 0, height=f.get("h") or 0,
                     preview_headers=HEADERS)
               for f in found]
