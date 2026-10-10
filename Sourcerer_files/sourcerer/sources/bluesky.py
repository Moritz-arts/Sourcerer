"""Bluesky. Public posts need no login.

Files are fetched as the original blob from the account's own server (its
PDS), not from the CDN, which hands out recompressed JPEGs and video as a
stream playlist. The blob's id (its CID) names the file and keys it.
"""
import re
import urllib.parse

from .. import net

KIND = "bluesky"
LABEL = "Bluesky"

API = "https://public.api.bsky.app/xrpc/"
_URL = re.compile(r"^https?://(?:www\.)?bsky\.app/profile/([^/?#\s]+)", re.I)
PAGE = 100   # the API's maximum


def match(url):
    return bool(_URL.match(url.strip()))


def normalize(url):
    """https://bsky.app/profile/<handle>, also from a post's link."""
    return "https://bsky.app/profile/%s" % _URL.match(url.strip()).group(1)


def profile(url):
    actor = _URL.match(url.strip()).group(1)
    p = net.get_json(API + "app.bsky.actor.getProfile", {"actor": actor})
    return {"name": p.get("displayName") or p.get("handle") or "",
            "handle": "@" + p.get("handle", actor), "avatar": p.get("avatar") or ""}


def _pds(did):
    """The server that holds the account's files."""
    if did.startswith("did:web:"):
        doc = net.get_json("https://%s/.well-known/did.json" % did[8:])
    else:
        doc = net.get_json("https://plc.directory/" + urllib.parse.quote(did))
    for service in doc.get("service") or []:
        if service.get("id", "").endswith("#atproto_pds"):
            return service["serviceEndpoint"].rstrip("/")
    raise RuntimeError("no file server found for %s" % did)


def _blobs(embed):
    """(cid, mime) of every image or video in a post's embed."""
    if not embed:
        return
    kind = embed.get("$type", "")
    if kind == "app.bsky.embed.images":
        for image in embed.get("images") or []:
            yield _ref(image.get("image") or {})
    elif kind == "app.bsky.embed.video":
        yield _ref(embed.get("video") or {})
    elif kind == "app.bsky.embed.recordWithMedia":
        yield from _blobs(embed.get("media"))


def _ref(blob):
    # Current records: {"ref": {"$link": cid}}; the oldest ones: {"cid": cid}.
    return (blob.get("ref") or {}).get("$link") or blob.get("cid"), blob.get("mimeType", "")


def pages(url):
    from . import Media
    actor = _URL.match(url.strip()).group(1)
    did = net.get_json(API + "app.bsky.actor.getProfile", {"actor": actor})["did"]
    pds = _pds(did)
    cursor = None
    while True:
        feed = net.get_json(API + "app.bsky.feed.getAuthorFeed", {
            "actor": did, "filter": "posts_with_media", "limit": PAGE, "cursor": cursor})
        page = []
        for item in feed.get("feed") or []:
            post = item.get("post") or {}
            # Reposts carry a reason; somebody else's work is not this artist's.
            if item.get("reason") or (post.get("author") or {}).get("did") != did:
                continue
            record = post.get("record") or {}
            rkey = post.get("uri", "").rsplit("/", 1)[-1]
            for cid, mime in _blobs(record.get("embed")):
                if not cid:
                    continue
                page.append(Media(
                    remote_key="bluesky:%s:%s" % (did, cid),
                    url="%s/xrpc/com.atproto.sync.getBlob?%s" % (
                        pds, urllib.parse.urlencode({"did": did, "cid": cid})),
                    post_url="https://bsky.app/profile/%s/post/%s" % (did, rkey),
                    posted=record.get("createdAt") or post.get("indexedAt") or "",
                    # Bluesky keeps no file names; the blob's id stands in for one.
                    name=cid[-16:], mime=mime, filename=cid))
        yield page
        cursor = feed.get("cursor")
        if not cursor or not feed.get("feed"):
            return
