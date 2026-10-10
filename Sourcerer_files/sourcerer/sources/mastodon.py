"""Mastodon and other servers speaking its API (the fediverse). Public posts need no login.

A profile URL is https://<server>/@<user> (or /users/<user>). For an account
from another server seen through this one (https://a.social/@user@b.social),
b.social is asked directly: only an account's own server has all its posts.
"""
import re
import urllib.parse

from .. import net

KIND = "mastodon"
LABEL = "Mastodon"

_URL = re.compile(r"^https?://([^/\s]+)/(?:@|users/)([^/@?#\s]+)(?:@([^/?#\s]+))?", re.I)
# Sites whose profile links look like the fediverse's (/@name, /users/name)
# but are not -- pixiv's /users/123 was once taken for a Mastodon account.
_NOT_FEDIVERSE = {"youtube.com", "tiktok.com", "medium.com", "threads.net", "threads.com",
                  "bsky.app", "linktr.ee", "pixiv.net", "deviantart.com", "x.com",
                  "twitter.com", "patreon.com", "instagram.com", "facebook.com",
                  "reddit.com", "tumblr.com", "artstation.com", "github.com"}
PAGE = 40   # the API's maximum


def _parse(url):
    m = _URL.match(url.strip())
    host = m.group(1).lower() if m else ""
    if not m or host in _NOT_FEDIVERSE or host.split(".", 1)[-1] in _NOT_FEDIVERSE:
        return None
    server, user, home = m.group(1), m.group(2), m.group(3)
    return (home or server), user


def match(url):
    return _parse(url) is not None


def pages(url):
    server, user = _parse(url)
    base = "https://%s/api/v1" % server
    account = net.get_json(base + "/accounts/lookup", {"acct": user})
    max_id = None
    while True:
        statuses = net.get_json(base + "/accounts/%s/statuses" % account["id"], {
            "only_media": "true", "exclude_reblogs": "true", "limit": PAGE, "max_id": max_id})
        if not statuses:
            return
        page = []
        for status in statuses:
            for media in status.get("media_attachments") or []:
                if media.get("type") not in ("image", "gifv", "video", "audio"):
                    continue
                src = media.get("url") or media.get("remote_url")
                if not src:
                    continue
                page.append(_media(server, status, media, src))
        yield page
        max_id = statuses[-1]["id"]


def _media(server, status, media, src):
    from . import Media
    return Media(remote_key="mastodon:%s:%s" % (server.lower(), media["id"]),
                 url=urllib.parse.urljoin("https://%s/" % server, src),
                 post_url=status.get("url") or status.get("uri") or "",
                 posted=status.get("created_at") or "",
                 name=str(media["id"]))
