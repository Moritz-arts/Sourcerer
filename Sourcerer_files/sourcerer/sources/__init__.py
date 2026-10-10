"""One module per site. Each offers:

    KIND, LABEL          the stored kind and its name on screen
    match(url) -> bool   whether a profile URL belongs to this site
    pages(url)           yields lists of Media, newest first, one API page each

A site that is not here yet is still accepted as a source and shown as "not
supported yet", so an artist card can list every place the artist posts.
"""
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
    name: str            # short id for the file name
    mime: str = ""       # content type when the site states it


def site_for(url):
    for site in SITES:
        if site.match(url):
            return site
    return None


def kind_of(url):
    site = site_for(url)
    return site.KIND if site else "unsupported"


def label(kind):
    return next((s.LABEL for s in SITES if s.KIND == kind), "Not supported yet")


# Sites an artist card may list before Sourcerer can download from them, so the
# card names them properly instead of showing a bare host.
_KNOWN = {"patreon.com": "Patreon", "x.com": "X", "twitter.com": "X", "pixiv.net": "Pixiv",
          "deviantart.com": "DeviantArt", "instagram.com": "Instagram",
          "artstation.com": "ArtStation", "tumblr.com": "Tumblr", "newgrounds.com": "Newgrounds",
          "furaffinity.net": "FurAffinity", "itaku.ee": "Itaku", "fanbox.cc": "Fanbox",
          "subscribestar.com": "SubscribeStar", "kemono.su": "Kemono", "inkbunny.net": "Inkbunny"}


def describe(url):
    """kind, label and whether Sourcerer can download from it yet."""
    site = site_for(url)
    if site:
        return {"kind": site.KIND, "label": site.LABEL, "supported": True}
    host = urllib.parse.urlparse(url).hostname or ""
    host = host[4:] if host.startswith("www.") else host
    name = _KNOWN.get(host) or _KNOWN.get(host.split(".", 1)[-1])
    if not name and ("/media/users/" in url or "/members/" in url):
        name = "XenForo"                       # its media gallery and member pages
    return {"kind": "unsupported", "label": name or host or url, "supported": False}
