"""X (Twitter). A profile's media timeline needs a logged-in account: log in
under Manage Accounts. Listing goes through gallery-dl (_gdl.py), which
keeps up with X's ever-changing web API; the files -- pbs.twimg.com at
name=orig, the highest-bitrate video -- need no login and are downloaded by
Sourcerer itself.

X locks accounts that read too much too fast. So the listing is paced
(sleep-request, a random gap), a rate limit ends the listing and X rests
for an hour or two (waiting it out and going on is what drains an account),
a locked account pauses X for a day or two instead of being worked around,
a first sync of a long-running account takes at most MAX_NEW files at a
time, and the day's files count against net.BUDGETS["x"].
"""
import random

import re

from . import _gdl
from .. import accounts, net

KIND = "x"
LABEL = "X"
MAX_NEW = 400
_URL = re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(?=[/?#]|$)", re.I)
# Paths of x.com that are not accounts.
_RESERVED = {"home", "i", "explore", "search", "settings", "notifications", "messages", "compose",
             "intent", "share", "hashtag", "login", "logout", "signup", "tos", "privacy", "jobs"}
OPTIONS = {"sleep-request": "2.0-4.0", "ratelimit": "abort", "locked": "abort",
           "retweets": False, "quoted": False, "text-tweets": False, "videos": True}
# The first page of a gallery takes two or three requests (the account, the timeline); at a scan's
# gap of 2-4 s each, somebody opening an artist waited ten seconds. A person scrolling x.com asks
# as often, so an open gallery reads at about half that gap -- still random, never regular.
OPEN_SLEEP = "1.0-2.0"
FOLLOWS_HOURS = 23        # follows.py reads the list of followed accounts at most this often
LOGIN = ("required", "X shows a profile's media only to logged-in accounts.")
FIELDS = {"url": "{_url!j}", "tweet": "{tweet_id!j}", "num": "{num!j}", "key": "{filename!j}",
          "ext": "{extension!j}", "date": '"{date:%Y-%m-%dT%H:%M:%SZ}"', "user": "{author[name]!j}",
          "type": "{type!j}", "w": "{width!j}", "h": "{height!j}"}


def match(url):
    m = _URL.match(url.strip())
    return bool(m) and m.group(1).lower() not in _RESERVED


def _name(url):
    return _URL.match(url.strip()).group(1)


def account_key(url):
    return "x"


def normalize(url):
    return "https://x.com/%s" % _name(url)


def _options():
    options = dict(OPTIONS, cookies=accounts.jar("x", fresh=True))
    if net.waiting():
        options["sleep-request"] = OPEN_SLEEP
    return options


def _run(fn, *args):
    from . import LoginRequired
    try:
        return fn(*args)
    except _gdl.Failed as e:
        text = str(e).lower()
        # An artist who blocked the account or protects their tweets says "...blocked your
        # account" -- not a lock of ours, and not a dead login either: only that source fails.
        if "blocked your account" in text or "tweets are protected" in text:
            raise RuntimeError("X: %s" % str(e).split(":", 1)[-1].strip()) from e
        if "temporarily locked" in text:       # gallery-dl: "Account temporarily locked"
            net.pause("https://x.com", random.uniform(24, 48) * 3600,
                      "X locked the account -- unlock it at x.com in your browser")
            raise net.SlowDown("X locked the account; Sourcerer leaves X alone for a day or two") from e
        if e.slow:
            net.pause("https://x.com", random.uniform(1, 2) * 3600, "X asked Sourcerer to slow down")
            raise net.SlowDown("X asked Sourcerer to slow down; it rests for a while") from e
        if e.auth:
            raise LoginRequired("X: log in" + (" again" if accounts.logged_in("x") else "")) from e
        raise


FOLLOW_TIMEOUT = 900     # seconds: a list of thousands, one request per hundred with gallery-dl's gaps
HOME_FILES = 300         # the Following timeline is read as far as this many media files: who posted lately, not the whole list


def _picture(url):
    return "" if not url or "default_profile" in url else url.replace("_normal.", "_400x400.")


def _followed(messages):
    """The accounts of gallery-dl's list of followed users (messages of type 6, one user each)."""
    out = []
    for m in messages:
        user = m[-1] if m and m[0] == 6 and isinstance(m[-1], dict) else None
        if not user:
            continue
        legacy = user.get("legacy") if isinstance(user.get("legacy"), dict) else {}
        core = user.get("core") if isinstance(user.get("core"), dict) else {}
        name = core.get("screen_name") or legacy.get("screen_name") or user.get("screen_name") or user.get("name")
        if not name or not _URL.match("https://x.com/%s" % name):
            continue
        out.append({"url": "https://x.com/%s" % name,
                    "name": core.get("name") or legacy.get("name") or user.get("nick") or name,
                    "avatar": _picture((user.get("avatar") or {}).get("image_url") or legacy.get("profile_image_url_https") or
                                       user.get("profile_image") or "")})
    return out


def _authors(messages, me):
    """The accounts that posted the files of a timeline (type 2 and 3 messages say whose tweet it is), once each."""
    out, seen = [], set()
    for m in messages:
        meta = m[-1] if m and m[0] in (2, 3) and isinstance(m[-1], dict) else {}
        user = meta.get("author") if isinstance(meta.get("author"), dict) else meta.get("user")
        if not isinstance(user, dict):
            continue
        name = user.get("name")
        if not name or name.lower() in seen or str(user.get("id")) == me or not _URL.match("https://x.com/%s" % name):
            continue
        seen.add(name.lower())
        out.append({"url": "https://x.com/%s" % name, "name": user.get("nick") or name,
                    "avatar": _picture(user.get("profile_image") or "")})
    return out


def following(key):
    """(list name, pages[, note]) of the accounts the login follows: [{"url", "name", "avatar"}], newest follow first.
    The whole list is gallery-dl's `/id:<number>/following` (the number is the login's own `twid` cookie), printed at the
    end (-j) -- one go, once a day at most (follows.HOURS). When that does not come -- no twid in the saved login, X
    changed the endpoint, an empty answer -- the accounts of the Following timeline (https://x.com/home, what the
    page shows after the login) are taken instead: only those that posted media lately, but never nothing, and the
    note says why the full list is missing."""
    from . import LoginRequired
    twid = accounts.jar("x").get("twid") or ""
    me = re.sub(r"\D", "", twid.rpartition("%3D")[2] or twid.rpartition("=")[2])
    if not _gdl.available():
        raise RuntimeError("X's list needs gallery-dl, which did not install: Settings > Repair")
    problem = ""
    net._stopped("https://x.com")
    if me:
        try:
            messages = _run(_gdl.info, "https://x.com/id:%s/following" % me, "twitter", _options(), FOLLOW_TIMEOUT)
            net.spend("https://x.com", max(1, len(messages) // 50))
            out = _followed(messages)
            problem = "" if out else "X's list of followed accounts came back empty"
        except (net.SlowDown, LoginRequired):
            raise
        except Exception as e:
            out, problem = [], net.reason(e)
    else:
        out, problem = [], "the saved login has no twid cookie, so X's own account is unknown"
    note = ""
    if not out:
        try:
            net._stopped("https://x.com")
            messages = _run(_gdl.info, "https://x.com/home", "twitter", dict(_options(), **{"file-range": "1-%d" % HOME_FILES}), FOLLOW_TIMEOUT)
            net.spend("https://x.com", max(1, len(messages) // 50))
            out = _authors(messages, me)
        except (net.SlowDown, LoginRequired):
            raise
        except Exception as e:
            raise RuntimeError("%s; the Following timeline did not work either: %s" % (problem, net.reason(e))) from e
        if not out:
            raise RuntimeError("%s; the Following timeline showed no account" % problem)
        note = "%s -- the %d accounts of the Following timeline were taken instead (log in to X again if the full list should come)" % (problem, len(out))
    yield "home" if note else "", [out[i:i + 100] for i in range(0, len(out), 100)], note


def profile(url):
    """Who the account is. X shows this to guests too."""
    if not _gdl.available():
        raise RuntimeError("X needs gallery-dl, which did not install: Settings > Repair")
    net._stopped("https://x.com")
    messages = _run(_gdl.info, "https://x.com/%s/info" % _name(url), "twitter", _options())
    user = next((m[-1] for m in messages if m and m[0] == 2 and isinstance(m[-1], dict)), {})
    return {"name": user.get("nick") or user.get("name") or _name(url),
            "handle": "@" + (user.get("name") or _name(url)),
            # The default egg is no picture of the artist.
            "avatar": "" if "default_profile" in (user.get("profile_image") or "") else
                      user.get("profile_image") or ""}


def pages(url):
    from . import LoginRequired, Media
    if not _gdl.available():
        raise RuntimeError("X needs gallery-dl, which did not install: Settings > Repair")
    if not accounts.logged_in("x"):
        raise LoginRequired("X shows a profile's media only to a logged-in account")
    net._stopped("https://x.com")
    listing = _gdl.items("https://x.com/%s/media" % _name(url), "twitter", _options(), FIELDS)
    while True:
        net._stopped("https://x.com")      # spent or refused meanwhile: gallery-dl cannot see a pause
        try:
            batch = _run(next, listing)
        except StopIteration:
            return
        net.spend("https://x.com", len(batch))
        yield [Media(remote_key="x:%s:%s" % (f["tweet"], f["num"]), url=f["url"],
                     post_url="https://x.com/%s/status/%s" % (f.get("user") or _name(url), f["tweet"]),
                     posted=f.get("date") or "", name="%s_%s" % (f["tweet"], f["num"]),
                     filename="%s.%s" % (f["key"], f["ext"]) if f.get("key") else "",
                     **_previews(f))
               for f in batch]


def _previews(f):
    """X's own sizes of a picture (name=small, 680 px; name=large); a video
    plays from its mp4."""
    src = f.get("url") or ""
    if "pbs.twimg.com/media/" in src:
        size = lambda name: re.sub(r"([?&]name=)\w+", r"\g<1>" + name, src) if "name=" in src else \
            src + ("&" if "?" in src else "?") + "name=" + name
        return {"thumb": size("small"), "large": size("large"), "width": f.get("w") or 0, "height": f.get("h") or 0}
    return {"large": src, "video": True, "width": f.get("w") or 0, "height": f.get("h") or 0}
