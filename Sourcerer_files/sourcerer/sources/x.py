"""X (Twitter). A profile's media timeline needs a logged-in account: log in
under Settings > Accounts. Listing goes through gallery-dl (_gdl.py), which
keeps up with X's ever-changing web API; the files -- pbs.twimg.com at
name=orig, the highest-bitrate video -- need no login and are downloaded by
Sourcerer itself.

X locks accounts that read too much too fast. So the listing is paced
(sleep-request), a rate limit is waited out as X asks rather than retried,
a locked account stops the sync instead of being worked around, and a first
sync of a long-running account takes at most MAX_NEW files at a time.
"""
import re

from . import _gdl
from .. import accounts

KIND = "x"
LABEL = "X"
MAX_NEW = 800
_URL = re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(?=[/?#]|$)", re.I)
# Paths of x.com that are not accounts.
_RESERVED = {"home", "i", "explore", "search", "settings", "notifications", "messages", "compose",
             "intent", "share", "hashtag", "login", "logout", "signup", "tos", "privacy", "jobs"}
OPTIONS = {"sleep-request": "1.5-3.0", "ratelimit": "wait", "locked": "abort",
           "retweets": False, "quoted": False, "text-tweets": False, "videos": True}
FIELDS = {"url": "{_url!j}", "tweet": "{tweet_id!j}", "num": "{num!j}", "key": "{filename!j}",
          "ext": "{extension!j}", "date": '"{date:%Y-%m-%dT%H:%M:%SZ}"', "user": "{author[name]!j}"}


def match(url):
    m = _URL.match(url.strip())
    return bool(m) and m.group(1).lower() not in _RESERVED


def _name(url):
    return _URL.match(url.strip()).group(1)


def normalize(url):
    return "https://x.com/%s" % _name(url)


def _options():
    return dict(OPTIONS, cookies=accounts.jar("x"))


def _run(fn, *args):
    from . import LoginRequired
    try:
        return fn(*args)
    except _gdl.Failed as e:
        if e.auth:
            raise LoginRequired("X: log in" + (" again" if accounts.logged_in("x") else "")) from e
        raise


def profile(url):
    """Who the account is. X shows this to guests too."""
    if not _gdl.available():
        raise RuntimeError("X needs gallery-dl, which did not install: Settings > Repair")
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
    listing = _gdl.items("https://x.com/%s/media" % _name(url), "twitter", _options(), FIELDS)
    while True:
        try:
            batch = _run(next, listing)
        except StopIteration:
            return
        yield [Media(remote_key="x:%s:%s" % (f["tweet"], f["num"]), url=f["url"],
                     post_url="https://x.com/%s/status/%s" % (f.get("user") or _name(url), f["tweet"]),
                     posted=f.get("date") or "", name="%s_%s" % (f["tweet"], f["num"]),
                     filename="%s.%s" % (f["key"], f["ext"]) if f.get("key") else "")
               for f in batch]
