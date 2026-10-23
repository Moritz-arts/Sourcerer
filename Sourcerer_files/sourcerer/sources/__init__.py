"""One module per site. Each offers:

    KIND, LABEL          the stored kind and its name on screen
    match(url) -> bool   whether a profile URL belongs to this site
    normalize(url)       the profile URL behind any page of it (a post, /media, ...)
    profile(url)         {"name", "handle", "avatar", "links", "mentions"}: who the account is; links (optional): the other
                         accounts its own profile names -- see profile_links; mentions (optional): the ones its bio
                         names -- see bio_links
    pages(url)           yields lists of Media, newest first, one API page each
    MAX_NEW (optional)   at most this many new files per sync; the next carries on
    account_key(url)     the login (accounts.py) a source uses, if the site has logins
    LOGIN (optional)     ("required" or "recommended", why) -- said in the card dialog
                         while that login is missing; login_need(url) where it varies
    still_logged_in(key) (optional) whether the site still takes a saved login

A site that is not here yet is still accepted as a source and shown as "not
supported yet", so an artist card can list every place the artist posts.
"""
import html
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass

from . import bluesky, booru, fanbox, fantia, mastodon, misskey, patreon, pixiv, x, xenforo

# booru before mastodon: a booru's /users/ pages look like the fediverse's. misskey too: its profile
# links are Mastodon's, told apart by the server (known or learned).
SITES = [bluesky, pixiv, x, patreon, fanbox, fantia, xenforo, booru, misskey, mastodon]
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
    """The site shows this only to members: log in under Manage Accounts."""


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
FIELDS = [("Bluesky", "bsky.app/profile/name"), ("Mastodon", "mastodon.social/@name"), ("Misskey", "misskey.io/@name"),
          ("XenForo", "forum.example/media/users/name.123"), ("Patreon", "patreon.com/name"),
          ("X", "x.com/name"), ("Pixiv", "pixiv.net/users/12345"), ("Fanbox", "name.fanbox.cc"), ("Fantia", "fantia.jp/fanclubs/12345"),
          ("Booru", "danbooru.donmai.us/posts?tags=artist_name")]


# Sites an artist card may list before Sourcerer can download from them, so the
# card names them properly instead of showing a bare host.
_KNOWN = {"patreon.com": "Patreon", "x.com": "X", "twitter.com": "X", "pixiv.net": "Pixiv",
          "deviantart.com": "DeviantArt", "instagram.com": "Instagram",
          "artstation.com": "ArtStation", "tumblr.com": "Tumblr", "newgrounds.com": "Newgrounds",
          "furaffinity.net": "FurAffinity", "itaku.ee": "Itaku",
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


MANY = ("mastodon", "misskey", "xenforo", "booru")    # kinds that are many sites: each is told by its own name and icon


def site_name(url):
    """The website's own name. Mastodon, Misskey, XenForo and the boorus are software that many sites run: "Mastodon" says
    nothing about which server, so a card's account is under the server (baraag.net), the forum's host or the booru's name.
    The other kinds are one site each: their LABEL."""
    site = site_for(url)
    if not site:
        return describe(url)["label"]
    if site.KIND == "booru":
        from . import booru
        return booru.BOORUS.get(_host(url), (None, _host(url)))[1]
    return _host(url) or site.LABEL if site.KIND in MANY else site.LABEL


def describe(url):
    """kind, label (the software or site: what the login and the card dialog go by), site (the website's own name, see
    site_name), host, and whether Sourcerer can download from it yet."""
    site = site_for(url)
    if site:
        return {"kind": site.KIND, "label": site.LABEL, "supported": True, "site": site_name(url), "host": _host(url)}
    name = _known(url)
    if not name and ("/media/users/" in url or "/members/" in url):
        name = "XenForo"                       # its media gallery and member pages
    label = name or _host(url) or url
    return {"kind": "unsupported", "label": label, "supported": False, "site": label, "host": _host(url)}


_TEXT_URL = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)
_PIXIV_USER = re.compile(r"^(?:/[a-z]{2})?/users/\d+/?$")
MAX_LINKS = 20


def profile_links(*things):
    """The accounts on sites Sourcerer knows that a profile names itself -- its bio, its fields, the links it declares
    (pixiv's `social`, Fanbox's `profileLinks`, a Mastodon field): the strongest sign that two accounts are one artist,
    which no display name is. Each as the profile address a card would keep, lower-cased; no request is made (a pixiv work's
    link would need one: only pixiv's own profile addresses count). things: strings (text or HTML), lists and dicts of them."""
    out, todo = [], list(things)
    while todo:
        t = todo.pop(0)
        if isinstance(t, dict):
            todo += list(t.values())
        elif isinstance(t, (list, tuple)):
            todo += list(t)
        elif isinstance(t, str):
            for raw in _TEXT_URL.findall(html.unescape(t)):
                raw = raw.rstrip(".,;:!?)」。、")
                site = site_for(raw)
                if not site or (site.KIND == "pixiv" and not _PIXIV_USER.match(urllib.parse.urlsplit(raw).path)):
                    continue
                try:
                    url = site.normalize(raw).lower()
                except Exception:
                    continue
                if url not in out:
                    out.append(url)
    return out[:MAX_LINKS]


_TAG = re.compile(r"<[^>]*>")
_HREF = re.compile(r"""href=["']([^"']+)["']""", re.I)
# A bio writes "x.com/name" without the scheme and "@name@server" for the fediverse; both name an account all the same.
_BARE = re.compile(r"(?<![\w@./:-])((?:www\.)?(?:x\.com|twitter\.com|bsky\.app|pixiv\.net|fantia\.jp|patreon\.com)/[^\s\"'<>)\]]+"
                   r"|[\w-]+\.fanbox\.cc\b/?)", re.I)
_FEDI = re.compile(r"(?<![\w@.])@([\w.-]{2,30})@((?:[\w-]+\.)+[a-z]{2,})\b", re.I)


def bio_links(*things):
    """The accounts a bio (its text or HTML) names: the weaker sign, next to profile_links. An artist often says where else they
    are, but a bio names friends and collaborators as often -- so these only *suggest* (the merge dialog); nothing combines by
    them. Same form as profile_links; things: strings (text or HTML), lists and dicts of them."""
    texts, todo = [], list(things)
    while todo:
        t = todo.pop(0)
        if isinstance(t, dict):
            todo += list(t.values())
        elif isinstance(t, (list, tuple)):
            todo += list(t)
        elif isinstance(t, str):
            texts.append(t)
    found = []
    for t in texts:
        found += _HREF.findall(t)                           # HTML: the address is in the href, the shown text may be cut short
        plain = html.unescape(_TAG.sub(" ", t))
        found.append(plain)
        found += ["https://" + m.group(1) for m in _BARE.finditer(plain)]
        found += ["https://%s/@%s" % (m.group(2), m.group(1)) for m in _FEDI.finditer(plain)]
    return profile_links(found)


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
