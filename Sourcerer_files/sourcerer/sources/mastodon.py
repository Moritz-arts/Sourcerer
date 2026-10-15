"""Mastodon and other servers speaking its API (the fediverse). Public posts need no login.

A profile URL is https://<server>/@<user> (or /users/<user>). For an account
from another server seen through this one (https://a.social/@user@b.social),
b.social is asked directly: only an account's own server has all its posts.

Some servers show their API to logged-in users only (401), and followers-only
posts need a follower's login. A login is per server ("mastodon:<server>"):
Sourcerer registers itself there as an app and the server's own "Authorize"
page, opened in the login window, hands out a read-only token (OAuth, with
the out-of-band redirect desktop apps use). The token goes with this
server's API requests only.
"""
import re
import urllib.parse

import requests

from .. import accounts, config, net

KIND = "mastodon"
LABEL = "Mastodon"
OOB = "urn:ietf:wg:oauth:2.0:oob"
SCOPES = "read"

_URL = re.compile(r"^https?://([^/\s]+)/(?:@|users/)([^/@?#\s]+)(?:@([^/?#\s]+))?", re.I)
# Sites whose profile links look like the fediverse's (/@name, /users/name)
# but are not -- pixiv's /users/123 was once taken for a Mastodon account.
_NOT_FEDIVERSE = {"youtube.com", "tiktok.com", "medium.com", "threads.net", "threads.com",
                  "bsky.app", "linktr.ee", "pixiv.net", "deviantart.com", "x.com",
                  "twitter.com", "patreon.com", "instagram.com", "facebook.com",
                  "reddit.com", "tumblr.com", "artstation.com", "github.com",
                  "donmai.us", "e621.net", "e926.net", "gelbooru.com", "rule34.xxx", "yande.re",
                  "konachan.com", "konachan.net", "safebooru.org", "aibooru.online"}
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


def normalize(url):
    """https://<server>/@<user>[@<home>], whatever page of the profile was given."""
    m = _URL.match(url.strip())
    return "https://%s/@%s%s" % (m.group(1), m.group(2), "@" + m.group(3) if m.group(3) else "")


def account_key(url):
    return "mastodon:" + _parse(url)[0].lower()


_dead = {}      # server -> the token it refused: not sent again (a new login is another token)


def _auth(server, force=False):
    data = accounts.secrets("mastodon:" + server.lower())
    if not data or (not force and _dead.get(server.lower()) == data["token"]):
        return None
    return {"Authorization": "Bearer " + data["token"]}


def _api(server, path, params=None):
    check = path == "accounts/verify_credentials"
    url, auth = "https://%s/api/v1/%s" % (server, path), _auth(server, force=check)
    try:
        try:
            return net.get_json(url, params, headers=auth)
        except requests.HTTPError as e:
            # A token the server took back makes even public reads a 401: read
            # as a visitor then. The account check says the login ran out. A
            # refused login is counted by net (three in a row rest the whole
            # server), so the token goes once only, not with every request.
            if not (auth and not check and e.response is not None and e.response.status_code == 401):
                raise
            _dead[server.lower()] = auth["Authorization"][7:]
            return net.get_json(url, params)
    except requests.HTTPError as e:
        # 401: a server whose API is for its users only (or a token it no
        # longer takes); 403 with a JSON answer: Pleroma's and Akkoma's way to
        # say the same. A 403 page is something else -- a bot check.
        r = e.response
        if r is not None and (r.status_code == 401 or (r.status_code == 403 and
                              "json" in r.headers.get("Content-Type", ""))):
            from . import LoginRequired
            raise LoginRequired("%s shows this to its logged-in users only" % server) from e
        raise


def _account(url):
    server, user = _parse(url)
    return server, _api(server, "accounts/lookup", {"acct": user})


# ---- logging in (Settings > Accounts) ---------------------------------------------------

def server_of(text):
    """The server a typed name or link stands for: baraag.net, https://baraag.net/@a."""
    text = text.strip()
    parsed = _parse(text) if "/" in text.split("://", 1)[-1] else None
    return (parsed[0] if parsed else
            urllib.parse.urlparse(text if "://" in text else "https://" + text).hostname or "").lower()


def start_login(server):
    """Sourcerer as an app on the server (asked for afresh with every login,
    so a server that forgot it does not matter), then the URL of the page
    where the user lets it read: (url, finish(code))."""
    app = net.post_json("https://%s/api/v1/apps" % server, data={
        "client_name": "Sourcerer", "redirect_uris": OOB, "scopes": SCOPES,
        "website": "https://github.com/%s" % config.REPO})
    url = "https://%s/oauth/authorize?%s" % (server, urllib.parse.urlencode({
        "client_id": app["client_id"], "response_type": "code", "redirect_uri": OOB, "scope": SCOPES}))

    def finish(code):
        token = net.post_json("https://%s/oauth/token" % server, data={
            "grant_type": "authorization_code", "code": code, "client_id": app["client_id"],
            "client_secret": app["client_secret"], "redirect_uri": OOB, "scope": SCOPES})["access_token"]
        me = net.get_json("https://%s/api/v1/accounts/verify_credentials" % server,
                          headers={"Authorization": "Bearer " + token})
        accounts.save_token("mastodon:" + server, "login window", token=token,
                            user="@%s@%s" % (me.get("username", "?"), server),
                            client_id=app["client_id"], client_secret=app["client_secret"])
    return url, finish


def logout(key):
    """Take the token back on the server too (Settings there lists Sourcerer until then)."""
    data = accounts.load(key) or {}
    if not data.get("token") or not data.get("client_id"):
        return
    try:
        net.post_json("https://%s/oauth/revoke" % key.split(":", 1)[1], data={
            "client_id": data["client_id"], "client_secret": data["client_secret"], "token": data["token"]})
    except Exception as e:
        import logging
        logging.getLogger(__name__).info("%s: token not revoked: %s", key, net.reason(e))


def still_logged_in(key):
    server = key.split(":", 1)[1]
    try:
        _api(server, "accounts/verify_credentials")
        return True
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            return False
        raise
    except Exception as e:
        if e.__class__.__name__ == "LoginRequired":
            return False
        raise


def profile(url):
    server, account = _account(url)
    # Display names carry custom emoji as :shortcode:, which no folder should.
    name = re.sub(r":[\w+-]+:", "", account.get("display_name") or "").strip()
    avatar = account.get("avatar_static") or account.get("avatar") or ""
    return {"name": name or account.get("username") or "",
            "handle": "@%s@%s" % (account.get("username", ""), server),
            # An account without a picture gets the server's placeholder.
            "avatar": "" if avatar.endswith("/missing.png") else avatar}


def pages(url):
    server, account = _account(url)
    max_id = None
    while True:
        statuses = _api(server, "accounts/%s/statuses" % account["id"], {
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
    url = urllib.parse.urljoin("https://%s/" % server, src)
    return Media(remote_key="mastodon:%s:%s" % (server.lower(), media["id"]),
                 url=url,
                 post_url=status.get("url") or status.get("uri") or "",
                 posted=status.get("created_at") or "",
                 name=str(media["id"]),
                 # The name the server stored the upload under -- the uploader's
                 # own name is not published by Mastodon.
                 filename=urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]),
                 thumb=media.get("preview_url") or "", large=url,
                 video=media.get("type") in ("video", "gifv"),
                 width=((media.get("meta") or {}).get("original") or {}).get("width") or 0,
                 height=((media.get("meta") or {}).get("original") or {}).get("height") or 0)
