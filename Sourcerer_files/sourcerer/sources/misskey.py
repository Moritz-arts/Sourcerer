"""Misskey and the servers built on it (Sharkey, Firefish, Iceshrimp...): misskey.io, misskey.design...
Public notes need no login; a server that shows them to its members only needs the MiAuth login
(`start_login`: Sourcerer's own window opens the server's "allow Sourcerer" page, the token is read
from the server). Mastodon follows some of them -- an artist on misskey.io shows up in a
Baraag follow list -- and answers nothing a Mastodon client asks, so they need a module of their own.

A profile URL is https://<server>/@<user>, exactly Mastodon's, so a server counts as Misskey only when
it is known to be one: the list below, a name that starts with "misskey.", or a server learned from a
Mastodon source that got a 404 and found a Misskey behind it (`learn`, kept in the setting
`misskey_hosts`). An account from another server seen through this one (https://a.io/@user@b.io) is
asked at b.io, where its notes are.

The whole API is POST with a JSON body, also what only reads (`net.post_read`). A file's `url` is the
one the server serves for it -- the original, or for an image the server's public copy of it -- and
its `thumbnailUrl` a small WebP.
"""
import re
import urllib.parse
import uuid

import requests

from .. import accounts, db, net

KIND = "misskey"
LABEL = "Misskey"
PAGE = 30           # notes a request (the API allows 100; a sync reads a few pages only)
PERMISSION = "read:account"     # what MiAuth asks the user to allow: enough to tell the token works

HOSTS = {"misskey.io", "misskey.design", "nijimiss.moe", "sushi.ski", "misskey.gg"}
_URL = re.compile(r"^https?://([^/\s]+)/@([^/@?#\s]+)(?:@([^/?#\s]+))?", re.I)
_learned = None      # servers found to be Misskey (loaded on first use)
_tried = set()       # servers asked once and found not to be: not asked again until a restart


def _extra():
    global _learned
    if _learned is None:
        try:
            _learned = {h for h in (db.get_setting("misskey_hosts", "") or "").split(",") if h}
        except Exception:                    # the database is not there yet (a start, a test): the known list only
            return set()
    return _learned


def _known(host):
    host = host.lower()
    return host in HOSTS or host.startswith("misskey.") or host in _extra()


def _parse(url):
    m = _URL.match(url.strip())
    if not m:
        return None
    home = (m.group(3) or m.group(1)).lower()
    return (home, m.group(2)) if _known(home) else None


def match(url):
    return _parse(url) is not None


def normalize(url):
    """https://<server>/@<user>[@<home>], whatever page of the profile was given."""
    m = _URL.match(url.strip())
    return "https://%s/@%s%s" % (m.group(1), m.group(2), "@" + m.group(3) if m.group(3) else "")


def probe(host):
    """Whether host is a Misskey: Mastodon's API answered 404, and Misskey's /api/meta says who the
    server is. Remembered either way (a server that is not is not asked again)."""
    host = host.lower()
    if host in _tried or _known(host):
        return _known(host)
    try:
        meta = net.post_read("https://%s/api/meta" % host, json={"detail": False})
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code < 500:
            _tried.add(host)                 # a server that answers 404 here is no Misskey
        return False
    except Exception:
        return False                         # no answer proves nothing: asked again next time
    if isinstance(meta, dict) and meta.get("version") and "name" in meta:
        _extra().add(host)
        db.set_setting("misskey_hosts", ",".join(sorted(_extra())))
        return True
    _tried.add(host)
    return False


_dead = {}           # server -> the token it refused: not sent again (a new login is another token)


def account_key(url):
    return "misskey:" + _parse(url)[0]


def _token(host, force=False):
    data = accounts.secrets("misskey:" + host.lower())
    if not data or (not force and _dead.get(host.lower()) == data["token"]):
        return None
    return data["token"]


def _api(host, endpoint, body, force=False):
    token = _token(host, force)
    send = dict(body, i=token) if token else body
    # The token goes in the body (every version reads it there) and in the header, which is how net knows it
    # is a login's request and paces it.
    headers = {"Authorization": "Bearer " + token} if token else None
    try:
        return net.post_read("https://%s/api/%s" % (host, endpoint), json=send, headers=headers)
    except requests.HTTPError as e:
        r = e.response
        code = ""
        try:
            code = (r.json().get("error") or {}).get("code") or ""
        except Exception:
            pass
        if code == "NO_SUCH_USER":
            raise LookupError("%s has no such account" % host) from e
        # A token the server took back refuses even public reads: read as a visitor from now on. The account
        # check says the login ran out.
        if token and not force and code == "AUTHENTICATION_FAILED":
            _dead[host.lower()] = token
            return _api(host, endpoint, body)
        # A server that shows its notes to members only (401/403 with a JSON answer, not a bot check's page).
        if r is not None and r.status_code in (401, 403) and "json" in r.headers.get("Content-Type", ""):
            from . import LoginRequired
            raise LoginRequired("%s shows this to its logged-in users only" % host) from e
        raise


# ---- logging in (Manage Accounts) ---------------------------------------------------

def start_login(host):
    """MiAuth: the page where the user lets Sourcerer read, and what the window waits for. The page shows no code
    and has no address to read it from, so the server is asked for the session's answer: (url, ask, finish)."""
    session = str(uuid.uuid4())
    url = "https://%s/miauth/%s?%s" % (host, session, urllib.parse.urlencode({
        "name": "Sourcerer", "permission": PERMISSION}))
    tick = [0]

    def ask(_window):
        tick[0] += 1
        if tick[0] % 2:                    # every 3 s, not with every look of the window
            return None
        try:
            answer = net.post_read("https://%s/api/miauth/%s/check" % (host, session), json={})
        except Exception:
            return None
        return answer if isinstance(answer, dict) and answer.get("ok") and answer.get("token") else None

    def finish(answer):
        user = answer.get("user") or {}
        accounts.save_token("misskey:" + host, "login window", token=answer["token"],
                            user="@%s@%s" % (user.get("username", "?"), host))
    return url, ask, finish


FOLLOWING = 100          # the API's limit for a page of a list of accounts
MAX_FOLLOW_PAGES = 200


def following(key):
    """(list name, pages) of the accounts the login follows, newest follow first: [{"url", "name", "avatar"}]. An account
    of another server (a Mastodon one, which a Misskey can follow) is named by its own server's address."""
    host = key.split(":", 1)[1]
    me = _api(host, "i", {}, force=True)

    def pages():
        until, seen = None, set()
        while len(seen) < MAX_FOLLOW_PAGES:
            body = {"userId": me["id"], "limit": FOLLOWING}
            if until:
                body["untilId"] = until
            rows = _api(host, "users/following", body)
            if not rows or rows[-1]["id"] in seen:
                return
            seen.add(rows[-1]["id"])
            out = []
            for row in rows:
                who = row.get("followee") or {}
                if who.get("username"):
                    out.append({"url": "https://%s/@%s" % (who.get("host") or host, who["username"]),
                                "name": re.sub(r":[\w+-]+:", "", who.get("name") or "").strip() or who["username"],
                                "avatar": who.get("avatarUrl") or "", "links": _links(who),
                                "mentions": _mentions(who)})
            yield out
            until = rows[-1]["id"]
    yield "", pages()


def logout(key):
    """Take the token back on the server too, where it knows how (a Misskey of 2023 or later)."""
    data = accounts.load(key) or {}
    if not data.get("token"):
        return
    host = key.split(":", 1)[1]
    try:
        net.post_read("https://%s/api/i/revoke-token" % host, json={"token": data["token"], "i": data["token"]},
                      headers={"Authorization": "Bearer " + data["token"]})
    except Exception as e:
        import logging
        logging.getLogger(__name__).info("%s: token not revoked: %s", key, net.reason(e))


def still_logged_in(key):
    host = key.split(":", 1)[1]
    try:
        _api(host, "i", {}, force=True)
        return True
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            return False
        raise
    except Exception as e:
        if e.__class__.__name__ == "LoginRequired":
            return False
        raise


def _account(url):
    host, user = _parse(url)
    return host, _api(host, "users/show", {"username": user, "host": None})


def _links(account):
    """The accounts the profile declares in its fields (not its description: that names friends as often as itself)."""
    from . import profile_links
    return profile_links([f.get("value") for f in account.get("fields") or [] if isinstance(f, dict)])


def _mentions(account):
    from . import bio_links
    return bio_links(account.get("description"))


def profile(url):
    host, account = _account(url)
    # A display name carries custom emoji as :shortcode:, which no folder should.
    name = re.sub(r":[\w+-]+:", "", account.get("name") or "").strip()
    return {"name": name or account.get("username") or "",
            "handle": "@%s@%s" % (account.get("username", ""), host),
            "avatar": account.get("avatarUrl") or "",
            "links": _links(account), "mentions": _mentions(account)}


def pages(url):
    host, account = _account(url)
    until = None
    while True:
        # Both spellings of "replies too": the servers differ in which one they read and what they default to.
        body = {"userId": account["id"], "withFiles": True, "limit": PAGE, "withRenotes": False,
                "includeMyRenotes": False, "withReplies": True, "includeReplies": True}
        if until:
            body["untilId"] = until              # (a null is refused)
        notes = _api(host, "users/notes", body)
        if not notes:
            return
        yield [_media(host, note, f) for note in notes for f in note.get("files") or []
               if (f.get("type") or "").split("/")[0] in ("image", "video", "audio") and f.get("url")]
        until = notes[-1]["id"]


def _media(host, note, f):
    from . import Media
    props = f.get("properties") or {}
    return Media(remote_key="misskey:%s:%s" % (host, f["id"]),
                 url=f["url"],
                 post_url="https://%s/notes/%s" % (host, note["id"]),
                 posted=note.get("createdAt") or "",
                 name=str(f["id"]),
                 mime=f.get("type") or "",
                 # The name the server stored the upload under: the uploader's own ("image.png") is shared by thousands.
                 filename=urllib.parse.unquote(urllib.parse.urlparse(f["url"]).path.rsplit("/", 1)[-1]),
                 thumb=f.get("thumbnailUrl") or "", large=f["url"],
                 video=(f.get("type") or "").startswith("video/"),
                 width=props.get("width") or 0, height=props.get("height") or 0)
