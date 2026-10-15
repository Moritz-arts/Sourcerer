"""Bluesky. Public posts need no login.

Files are fetched as the original blob from the account's own server (its
PDS), not from the CDN, which hands out recompressed JPEGs and video as a
stream playlist. The blob's id (its CID) names the file and keys it.

A login (Manage Accounts) takes the handle and an app password -- a
password Bluesky makes for apps, which can be revoked on its own; the
account's real password is refused before it is sent. Logged in, the feed is
read through the user's own server, as Bluesky's app does. Today the public
API shows the same; the login is there for the day Bluesky closes it, as it
closed search. Kept is the session (90 days, renewed as it is used), never
the password -- Bluesky allows only a few new sessions a day.
"""
import base64
import json
import logging
import re
import threading
import time
import urllib.parse

import requests

from .. import accounts, net

log = logging.getLogger(__name__)

KIND = "bluesky"
LABEL = "Bluesky"

API = "https://public.api.bsky.app/xrpc/"
_URL = re.compile(r"^https?://(?:www\.)?bsky\.app/profile/([^/?#\s]+)", re.I)
PAGE = 100   # the API's maximum


def match(url):
    return bool(_URL.match(url.strip()))


def account_key(url):
    return "bluesky"


# ---- the login --------------------------------------------------------------------------

APPVIEW = {"atproto-proxy": "did:web:api.bsky.app#bsky_appview"}
# Bluesky's app passwords: 16 base32 characters in four groups.
_APP_PASSWORD = re.compile(r"^[a-z2-7]{4}(?:-[a-z2-7]{4}){3}$")
_refreshing = threading.Lock()


def _claims(jwt):
    try:
        part = jwt.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return {}


def _until(jwt):
    """When an access token runs out, by this computer's clock: its lifetime
    (exp - iat) from now -- a clock hours off would otherwise renew it before
    every call, or never."""
    c = _claims(jwt)
    return time.time() + max(60, (c.get("exp", 0) - c.get("iat", 0)) or 3600) - 60


def _pds_of(s, pds):
    """The PDS the session's DID document names: an account can move."""
    for service in ((s.get("didDoc") or {}).get("service") or []):
        if service.get("id", "").endswith("#atproto_pds") and service.get("serviceEndpoint"):
            return service["serviceEndpoint"].rstrip("/")
    return pds


def login(handle, password):
    """Open a session with an app password and keep it. ValueError says what was wrong."""
    handle, password = handle.strip().lstrip("@"), password.strip().lower()
    if not handle or not password:
        raise ValueError("Enter your handle and an app password.")
    if "@" in handle:
        raise ValueError("Enter your handle (name.bsky.social), not your e-mail address.")
    # Checked before anything is sent: the account's real password would open a
    # full session on Bluesky's side (and, with two-factor login, mail a code).
    if not _APP_PASSWORD.match(password):
        raise ValueError("That is not an app password (xxxx-xxxx-xxxx-xxxx). Create one in Bluesky "
                         "under Settings > Privacy and security > App passwords.")
    try:
        did = handle if handle.startswith("did:") else \
            net.get_json(API + "com.atproto.identity.resolveHandle", {"handle": handle})["did"]
        pds = _pds(did)
        s = net.post_json(pds + "/xrpc/com.atproto.server.createSession",
                          json={"identifier": did, "password": password})
    except requests.HTTPError as e:
        if _error(e) == "AuthFactorTokenRequired":
            raise ValueError("Bluesky asks for an e-mail code: use an app password instead.") from e
        if e.response is not None and e.response.status_code in (400, 401):
            raise ValueError("Bluesky did not accept this handle and app password.") from e
        raise
    if _claims(s["accessJwt"]).get("scope") == "com.atproto.access":
        _end(pds, s["refreshJwt"])
        raise ValueError("That is your account's password. Create an app password "
                         "(Bluesky: Settings > Privacy and security > App passwords) and use that.")
    accounts.save_token("bluesky", "app password", did=s["did"], user="@" + s.get("handle", handle),
                        pds=_pds_of(s, pds), access=s["accessJwt"], refresh=s["refreshJwt"],
                        access_until=_until(s["accessJwt"]))


def _end(pds, refresh):
    try:
        net.post_json(pds + "/xrpc/com.atproto.server.deleteSession",
                      headers={"Authorization": "Bearer " + refresh})
    except Exception as e:
        log.info("Bluesky session not ended: %s", net.reason(e))


def logout(key):
    """End the session on Bluesky's side too, before its file goes."""
    data = accounts.load("bluesky") or {}
    if data.get("refresh") and data.get("pds"):
        _end(data["pds"], data["refresh"])


def _error(e):
    try:
        return e.response.json().get("error") or ""
    except Exception:
        return ""


def _dead(e):
    """A session Bluesky no longer takes -- not a server that is down."""
    return isinstance(e, requests.HTTPError) and e.response is not None and (
        e.response.status_code == 401 or _error(e) in ("ExpiredToken", "InvalidToken"))


def _session(renew=False):
    """(pds, headers) of the saved login, its session renewed when it runs out; None logged out."""
    with _refreshing:
        data = accounts.secrets("bluesky")
        if not data:
            return None
        if renew or data.get("access_until", 0) < time.time():
            try:
                s = net.post_json(data["pds"] + "/xrpc/com.atproto.server.refreshSession",
                                  headers={"Authorization": "Bearer " + data["refresh"]})
            except requests.HTTPError as e:
                if _dead(e):
                    from . import LoginRequired
                    raise LoginRequired("Bluesky: log in again") from e
                raise
            data.update(access=s["accessJwt"], refresh=s["refreshJwt"], pds=_pds_of(s, data["pds"]),
                        access_until=_until(s["accessJwt"]))
            accounts.update("bluesky", access=data["access"], refresh=data["refresh"], pds=data["pds"],
                            access_until=data["access_until"])
        return data["pds"], {"Authorization": "Bearer " + data["access"]}


def still_logged_in(key):
    try:
        session = _session()
        if not session:
            return False
        for renew in (False, True):
            pds, headers = session
            try:
                net.get_json(pds + "/xrpc/com.atproto.server.getSession", headers=headers)
                return True
            except requests.HTTPError as e:
                if renew or _error(e) != "ExpiredToken":
                    raise
                session = _session(renew=True)
    except Exception as e:
        if e.__class__.__name__ == "LoginRequired" or _dead(e):
            return False
        raise


def _visitor_or(renew=False):
    """The login's session -- or None, read as a visitor, when it cannot be
    renewed: public posts need no login, and the account check says it ran out."""
    try:
        return _session(renew)
    except Exception as e:
        log.info("Bluesky login not usable (%s); reading as a visitor", net.reason(e))
        return None


def _get(method, params):
    """An app.bsky call: through the user's own server when logged in, else the public API."""
    session = _visitor_or()
    if not session:
        return net.get_json(API + method, params)
    for renew in (False, True):
        pds, headers = session
        try:
            return net.get_json("%s/xrpc/%s" % (pds, method), params, headers=dict(headers, **APPVIEW))
        except requests.HTTPError as e:
            if _error(e) in ("BlockedByActor", "BlockedActor"):
                raise RuntimeError("this artist blocked your Bluesky account, or you blocked them") from e
            if renew or _error(e) != "ExpiredToken":
                raise
            session = _visitor_or(renew=True)       # the token ran out before its time said so
            if not session:
                return net.get_json(API + method, params)


def normalize(url):
    """https://bsky.app/profile/<handle>, also from a post's link."""
    return "https://bsky.app/profile/%s" % _URL.match(url.strip()).group(1)


def profile(url):
    actor = _URL.match(url.strip()).group(1)
    p = _get("app.bsky.actor.getProfile", {"actor": actor})
    return {"name": p.get("displayName") or p.get("handle") or "",
            "handle": "@" + p.get("handle", actor), "avatar": p.get("avatar") or ""}


def _pds(did):
    """The server that holds the account's files."""
    if did.startswith("did:web:"):
        doc = net.get_json("https://%s/.well-known/did.json" % urllib.parse.unquote(did[8:]))
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


def _views(embed):
    """The post view's pictures, in the record's order: thumb and fullsize on
    Bluesky's CDN for the gallery (the files themselves still come from the PDS)."""
    if not embed:
        return
    kind = embed.get("$type", "")
    if kind.startswith("app.bsky.embed.images"):
        yield from embed.get("images") or []
    elif kind.startswith("app.bsky.embed.video"):
        yield embed
    elif kind.startswith("app.bsky.embed.recordWithMedia"):
        yield from _views(embed.get("media"))


def _ref(blob):
    # Current records: {"ref": {"$link": cid}}; the oldest ones: {"cid": cid}.
    return (blob.get("ref") or {}).get("$link") or blob.get("cid"), blob.get("mimeType", "")


def pages(url):
    from . import Media
    actor = _URL.match(url.strip()).group(1)
    did = _get("app.bsky.actor.getProfile", {"actor": actor})["did"]
    pds = _pds(did)
    cursor = None
    while True:
        feed = _get("app.bsky.feed.getAuthorFeed", {
            "actor": did, "filter": "posts_with_media", "limit": PAGE, "cursor": cursor})
        page = []
        for item in feed.get("feed") or []:
            post = item.get("post") or {}
            # Reposts carry a reason; somebody else's work is not this artist's.
            if item.get("reason") or (post.get("author") or {}).get("did") != did:
                continue
            record = post.get("record") or {}
            rkey = post.get("uri", "").rsplit("/", 1)[-1]
            views = list(_views(post.get("embed")))
            for i, (cid, mime) in enumerate(_blobs(record.get("embed"))):
                if not cid:
                    continue
                view = views[i] if i < len(views) else {}
                page.append(Media(
                    remote_key="bluesky:%s:%s" % (did, cid),
                    url="%s/xrpc/com.atproto.sync.getBlob?%s" % (
                        pds, urllib.parse.urlencode({"did": did, "cid": cid})),
                    post_url="https://bsky.app/profile/%s/post/%s" % (did, rkey),
                    posted=record.get("createdAt") or post.get("indexedAt") or "",
                    # Bluesky keeps no file names; the blob's id stands in for one.
                    name=cid[-16:], mime=mime, filename=cid,
                    thumb=view.get("thumb") or view.get("thumbnail") or "",
                    # A video plays from the blob itself: the view only offers a stream playlist.
                    large=view.get("fullsize") or "%s/xrpc/com.atproto.sync.getBlob?%s" % (
                        pds, urllib.parse.urlencode({"did": did, "cid": cid})),
                    video=mime.startswith("video/"),
                    width=(view.get("aspectRatio") or {}).get("width") or 0,
                    height=(view.get("aspectRatio") or {}).get("height") or 0))
        yield page
        cursor = feed.get("cursor")
        if not cursor or not feed.get("feed"):
            return
