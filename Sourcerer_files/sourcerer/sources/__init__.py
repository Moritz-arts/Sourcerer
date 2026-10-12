"""One module per site. Each offers:

    KIND, LABEL          the stored kind and its name on screen
    match(url) -> bool   whether a profile URL belongs to this site
    normalize(url)       the profile URL behind any page of it (a post, /media, ...)
    profile(url)         {"name", "handle", "avatar"}: who the account is
    pages(url)           yields lists of Media, newest first, one API page each
    MAX_NEW (optional)   at most this many new files per sync; the next carries on
    account_key(url)     the login (accounts.py) a source uses, if the site has logins
    LOGIN (optional)     ("required" or "recommended", why) -- said in the card dialog
                         while that login is missing; login_need(url) where it varies
    still_logged_in(key) (optional) whether the site still takes a saved login

A site that is not here yet is still accepted as a source and shown as "not
supported yet", so an artist card can list every place the artist posts.
"""
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass

from . import bluesky, booru, mastodon, patreon, pixiv, x, xenforo

# booru before mastodon: a booru's /users/ pages look like the fediverse's.
SITES = [bluesky, pixiv, x, patreon, xenforo, booru, mastodon]
log = logging.getLogger(__name__)


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
    # fetch(folder, progress) -> net.download's tuple, for a file whose address
    # costs a request of its own: asked for when it downloads, not while scanning.
    fetch: object = None
    # Glob patterns a copy already in the card's folder would match, where the
    # name is not known before the download (pixiv's hashed names).
    local: list = None
    # What the gallery shows, from the listing itself -- no request of its own.
    thumb: str = ""      # a small picture for the grid
    large: str = ""      # a screen-sized one for the viewer (or the file itself)
    video: bool = False  # large is a video
    width: int = 0
    height: int = 0
    # Headers the picture hosts want (pixiv, Gelbooru: a Referer): the gallery
    # then fetches thumb and large through Sourcerer instead of the page.
    preview_headers: dict = None


class LoginRequired(Exception):
    """The site shows this only to members: log in under Settings > Accounts."""


def site_for(url):
    for site in SITES:
        if site.match(url):
            return site
    return None


def account_key(url):
    """The login a source would use, or None for a site without logins."""
    site = site_for(url)
    fn = getattr(site, "account_key", None)
    return fn(url) if fn else None


def login_need(url):
    """(need, why): whether a link needs a login ("required"), works better with
    one ("recommended") or not at all (None, "")."""
    site = site_for(url)
    if not site:
        return None, ""
    fn = getattr(site, "login_need", None)
    return fn(url) if fn else getattr(site, "LOGIN", (None, ""))


def kind_of(url):
    site = site_for(url)
    return site.KIND if site else "unsupported"


# The card dialog's fixed fields, in this order, each with an example link.
# Any other link -- a second account, another site -- goes into a row below.
FIELDS = [("Bluesky", "bsky.app/profile/name"), ("Mastodon", "mastodon.social/@name"),
          ("XenForo", "forum.example/media/users/name.123"), ("Patreon", "patreon.com/name"),
          ("X", "x.com/name"), ("Pixiv", "pixiv.net/users/12345"),
          ("Booru", "danbooru.donmai.us/posts?tags=artist_name")]


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
        try:
            return site.normalize(url)
        except Exception as e:        # a work's link that needs a request: keep it as it is
            log.info("could not normalise %s: %s", url, e)
            return url
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


_profiles = {}            # url -> (when, answer): the card dialog, Save and the avatar ask alike
PROFILE_SECONDS = 1800


def profile(url):
    """{"name", "handle", "avatar"} of the account, or None for an unsupported site.
    Asked once per half hour: opening a card, saving it and looking for its
    picture all want it, and on X each asking is a logged-in request."""
    site = site_for(url)
    if not site:
        return None
    hit = _profiles.get(url)
    if hit and time.monotonic() - hit[0] < PROFILE_SECONDS:
        return dict(hit[1])
    answer = site.profile(url)
    if len(_profiles) > 500:
        _profiles.clear()
    _profiles[url] = (time.monotonic(), answer)
    return dict(answer)
