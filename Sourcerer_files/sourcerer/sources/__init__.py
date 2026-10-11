"""One module per site. Each offers:

    KIND, LABEL          the stored kind and its name on screen
    match(url) -> bool   whether a profile URL belongs to this site
    normalize(url)       the profile URL behind any page of it (a post, /media, ...)
    profile(url)         {"name", "handle", "avatar"}: who the account is
    pages(url)           yields lists of Media, newest first, one API page each

A site that is not here yet is still accepted as a source and shown as "not
supported yet", so an artist card can list every place the artist posts.
"""
import re
import urllib.parse
from dataclasses import dataclass

from . import bluesky, mastodon

SITES = [bluesky, mastodon]


@dataclass
class Media:
    remote_key: str      # unique per artist and file -- never downloaded twice
    url: str             # the original file, not a preview
    post_url: str
    posted: str          # ISO date the post was made
    name: str            # short id, the file name's last resort
    mime: str = ""       # content type when the site states it
    filename: str = ""   # the file's own name on the site, when it has one
    headers: dict = None  # what the file's host wants with the request (pixiv: a Referer)


class LoginRequired(Exception):
    """The site shows this only to members: log in under Settings > Accounts."""


def site_for(url):
    for site in SITES:
        if site.match(url):
            return site
    return None


def kind_of(url):
    site = site_for(url)
    return site.KIND if site else "unsupported"


# The card dialog's fixed fields, in this order, each with an example link.
# Any other link -- a second account, another site -- goes into a row below.
FIELDS = [("Bluesky", "bsky.app/profile/name"), ("Mastodon", "mastodon.social/@name"),
          ("XenForo", "forum.example/media/users/name.123"), ("Patreon", "patreon.com/name"),
          ("X", "x.com/name"), ("Pixiv", "pixiv.net/users/12345")]


# Sites an artist card may list before Sourcerer can download from them, so the
# card names them properly instead of showing a bare host.
_KNOWN = {"patreon.com": "Patreon", "x.com": "X", "twitter.com": "X", "pixiv.net": "Pixiv",
          "deviantart.com": "DeviantArt", "instagram.com": "Instagram",
          "artstation.com": "ArtStation", "tumblr.com": "Tumblr", "newgrounds.com": "Newgrounds",
          "furaffinity.net": "FurAffinity", "itaku.ee": "Itaku", "fanbox.cc": "Fanbox",
          "subscribestar.com": "SubscribeStar", "kemono.su": "Kemono", "inkbunny.net": "Inkbunny"}

# Pages of a profile that are still that profile: x.com/a/media, pixiv's
# /users/1/artworks, deviantart's /a/gallery. Cut back to the profile itself,
# so any of them can be pasted and the same source comes out.
_TAILS = {
    "X": r"^(/[^/?#]+)(?:/(?:media|with_replies|highlights|likes|status/.*|photo/.*))?/?$",
    "Pixiv": r"^((?:/[a-z]{2})?/users/\d+)(?:/(?:artworks|illustrations|manga|bookmarks/.*).*)?/?$",
    "DeviantArt": r"^(/[^/?#]+)(?:/(?:gallery|art|favourites|posts)(?:/.*)?)?/?$",
    "Instagram": r"^(/[^/?#]+)(?:/(?:reels|tagged|p/.*))?/?$",
    "Patreon": r"^(/(?:c/)?[^/?#]+)(?:/(?:posts|about|membership).*)?/?$",
}


def _host(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def _known(url):
    host = _host(url)
    return _KNOWN.get(host) or _KNOWN.get(host.split(".", 1)[-1])


def normalize(url):
    """https://, no trailing slash, and the profile behind any page of it."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    url = url.split("#", 1)[0].rstrip("/")
    site = site_for(url)
    if site:
        return site.normalize(url)
    name = _known(url)
    parts = urllib.parse.urlparse(url)
    if name in _TAILS:
        m = re.match(_TAILS[name], parts.path)
        if m:
            host = "x.com" if name == "X" else parts.netloc
            return urllib.parse.urlunparse((parts.scheme, host, m.group(1), "", "", ""))
    return url


def describe(url):
    """kind, label and whether Sourcerer can download from it yet."""
    site = site_for(url)
    if site:
        return {"kind": site.KIND, "label": site.LABEL, "supported": True}
    name = _known(url)
    if not name and ("/media/users/" in url or "/members/" in url):
        name = "XenForo"                       # its media gallery and member pages
    return {"kind": "unsupported", "label": name or _host(url) or url, "supported": False}


def profile(url):
    """{"name", "handle", "avatar"} of the account, or None for an unsupported site."""
    site = site_for(url)
    return site.profile(url) if site else None
