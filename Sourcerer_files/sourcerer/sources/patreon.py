"""Patreon. Public posts need no login; a patron's posts need the login made
under Settings > Accounts, whose session_id cookie net.py sends along.

Everything comes from /api/, the JSON:API Patreon's own website uses. Its HTML
pages sit behind a Cloudflare challenge that no plain HTTP client passes, so
none is read: the campaign behind a link comes from the API too.

Every file of a post -- gallery images, images inside the text, attachments --
is a "media" object whose download_url is the upload itself, byte for byte,
with the uploader's file name. image_urls.original is NOT the original but a
re-encode (a 14 MB PNG came back as 21 MB). A locked post lists media as well:
blurred previews and teaser clips, which are skipped with the post.
"""
import re
import time
import urllib.parse

import requests

from .. import accounts, net

KIND = "patreon"
LABEL = "Patreon"

API = "https://www.patreon.com/api/"
SITE = "https://www.patreon.com/"
PAGE = 50            # posts per request; the API takes far more, but a routine sync needs one page
_URL = re.compile(r"^https?://(?:www\.)?patreon\.com(/[^?#]*)?(?:\?([^#]*))?", re.I)
# First path segments that are Patreon's own pages, not a creator.
_NOT_CREATOR = {"home", "login", "signup", "search", "messages", "settings", "notifications", "create",
                "explore", "collection", "library", "checkout", "join", "policy", "api", "file",
                "media-u", "creation", "rss", "bepatron", "membership", "posts", "user", "profile", "m"}
# What a media object is to its post: main, inline, attachment -- or, in old
# posts (a 2014 mp3), nothing at all. These are teasers, download_url or not.
_TEASERS = {"clip_start_screen", "video_preview", "vertical_video_preview"}
_CAMPAIGN_FIELDS = "name,url,vanity,avatar_photo_url,avatar_photo_image_urls"
_campaigns = {}      # url -> (when, campaign): the profile and the pages of one sync ask once
CAMPAIGN_SECONDS = 600
LOGIN = ("recommended", "Logged out, only public posts come; a patron's posts need the login.")


def _parse(url):
    """("vanity", v), ("user", id), ("campaign", id), ("post", id) or None."""
    m = _URL.match((url or "").strip())
    if not m:
        return None
    parts = [p for p in (m.group(1) or "").split("/") if p]
    query = urllib.parse.parse_qs(m.group(2) or "")
    if not parts:
        return None
    first = parts[0].lower()
    if first in ("user", "profile") and query.get("u"):          # /user?u=1, /profile/creators?u=1
        return ("user", query["u"][0])
    if first in ("user", "profile") and query.get("c"):
        return ("campaign", query["c"][0])
    if first == "m" and len(parts) > 1 and parts[1].isdigit():   # /m/<campaign id>
        return ("campaign", parts[1])
    if first == "posts" and len(parts) > 1:                      # /posts/<slug>-<id>
        pid = re.search(r"(\d+)$", parts[1])
        return ("post", pid.group(1)) if pid else None
    if first in ("c", "cw") and len(parts) > 1:                  # /c/<vanity>, /cw/<vanity>
        return ("vanity", parts[1])
    if first in _NOT_CREATOR or not re.fullmatch(r"[\w.-]+", parts[0]):
        return None
    return ("vanity", parts[0])                                  # /<vanity>[/posts|/about|/posts/<slug>-<id>...]


def match(url):
    return _parse(url) is not None


def account_key(url):
    return "patreon"


def normalize(url):
    """https://www.patreon.com/<vanity>. A link without one (/user?u=, /posts/<id>)
    is looked up; when that fails, it is kept as given and pages() looks it up."""
    kind, value = _parse(url)
    if kind == "vanity":
        # Vanities are case-insensitive: one creator, one source.
        return SITE + value.lower()
    try:
        return SITE + _campaign(url)["attributes"]["vanity"].lower()
    except Exception:
        return url


def _campaign(url):
    when, camp = _campaigns.get(url, (0, None))
    if camp and time.monotonic() - when < CAMPAIGN_SECONDS:
        return camp
    kind, value = _parse(url)
    fields = {"fields[campaign]": _CAMPAIGN_FIELDS, "json-api-use-default-includes": "false"}
    if kind == "vanity":
        camp = net.get_json(API + "campaigns", dict(fields, **{"filter[vanity]": value}))["data"][0]
    elif kind == "campaign":
        camp = net.get_json(API + "campaigns/" + value, fields)["data"]
    else:
        # A user or a post: its campaign comes along as an inclusion.
        path, extra = ("user/%s" % value, {"fields[user]": "vanity"}) if kind == "user" else \
                      ("posts/%s" % value, {"fields[post]": "url"})
        doc = net.get_json(API + path, dict(fields, include="campaign", **extra))
        camp = next(i for i in doc.get("included") or [] if i["type"] == "campaign")
    _campaigns[url] = (time.monotonic(), camp)
    return camp


def profile(url):
    camp = _campaign(url)
    a = camp["attributes"]
    avatar = (a.get("avatar_photo_image_urls") or {}).get("thumbnail_large") or a.get("avatar_photo_url") or ""
    return {"name": a.get("name") or a.get("vanity") or "", "handle": a.get("vanity") or "",
            "avatar": avatar}


def pages(url):
    from . import LoginRequired, Media
    # A session_id that ran out does not make /api/posts fail: it quietly
    # answers as to a guest. So a saved login is asked about first.
    if accounts.logged_in("patreon") and whoami() is None:
        raise LoginRequired("Patreon: log in again")
    cid = _campaign(url)["id"]
    params = {"filter[campaign_id]": cid, "filter[contains_exclusive_posts]": "true",
              "filter[is_draft]": "false", "sort": "-published_at", "include": "media",
              "fields[post]": "current_user_can_view,published_at,url",
              "fields[media]": "download_url,file_name,mimetype,owner_relationship,size_bytes",
              "page[count]": PAGE, "json-api-use-default-includes": "false", "json-api-version": "1.0"}
    cursor = None
    while True:
        doc = net.get_json(API + "posts", dict(params, **({"page[cursor]": cursor} if cursor else {})))
        media = {i["id"]: i["attributes"] for i in doc.get("included") or [] if i["type"] == "media"}
        page = []
        for post in doc.get("data") or []:
            a = post["attributes"]
            # A post this account may not see still lists media: blurred previews.
            if not a.get("current_user_can_view"):
                continue
            for ref in ((post.get("relationships") or {}).get("media") or {}).get("data") or []:
                m = media.get(ref["id"]) or {}
                src = m.get("download_url") or ""
                # Only Patreon's file host serves uploads; /media-u/ on www is a
                # YouTube thumbnail of an embed. Patreon's own videos have no
                # download_url at all -- they are HLS streams with no file behind them.
                owner = m.get("owner_relationship") or ""
                if owner in _TEASERS or "preview" in owner or \
                        not (urllib.parse.urlparse(src).hostname or "").endswith(".patreonusercontent.com"):
                    continue
                # No size: the file is gone (yt-dlp #4608). Fetching it would fail on
                # every sync and keep the source from ever counting as complete.
                if m.get("size_bytes") is None:
                    continue
                name = m.get("file_name") or ""
                page.append(Media(
                    remote_key="patreon:%s" % ref["id"],
                    url=src, post_url=a.get("url") or "", posted=a.get("published_at") or "",
                    name=ref["id"], mime=m.get("mimetype") or "",
                    filename="" if "://" in name else name))
        yield page
        cursor = (((doc.get("meta") or {}).get("pagination") or {}).get("cursors") or {}).get("next")
        if not cursor or not doc.get("data"):
            return


def still_logged_in(key):
    return whoami() is not None


def whoami():
    """The logged-in account's name, or None when Patreon no longer takes the login."""
    try:
        doc = net.get_json(API + "current_user", {"fields[user]": "full_name",
                                                  "json-api-use-default-includes": "false"})
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            return None
        raise
    return doc["data"]["attributes"].get("full_name") or doc["data"]["id"]
