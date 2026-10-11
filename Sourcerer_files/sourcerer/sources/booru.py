"""Boorus: image boards that tag every picture, an artist's work under the artist's tag.

A source is a tag search as pasted from the site -- usually the artist's tag:
danbooru.donmai.us/posts?tags=wlop, gelbooru.com/index.php?page=post&s=list&tags=wlop,
yande.re/post?tags=wlop. An artist's page on a Danbooru-type site
(/artists/<id>) or one of its posts (/posts/<id>) is turned into that tag.

Three engines run nearly every booru, each with a JSON API of its own:

  danbooru  Danbooru and its forks: posts.json, paged with page=b<id>.
            e621 is a fork whose posts look different ("e621").
  gelbooru  Gelbooru 0.2: index.php?page=dapi, paged with the tag id:<N.
  moebooru  yande.re, konachan: post.json, paged with id:<N as well.

Every listing is newest first; the cursor is the lowest id seen, so posts
added meanwhile cannot shift a page. Files are the originals (file_url),
keyed by the post id -- "booru:<host>:<id>", forever.

Logins are a user name and the API key the site shows in its account
settings ("booru:<host>"). gelbooru.com and rule34.xxx answer their API only
with one; e621 leaves out the files of some posts without one; Danbooru and
Moebooru show logged-out visitors nearly everything.
"""
import base64
import datetime
import html
import json
import re
import urllib.parse

import requests

from .. import accounts, net

KIND = "booru"
LABEL = "Booru"
MAX_NEW = 1000            # a big tag's first sync is spread over several

# host: (engine, name, login (None, "optional", "recommended", "required"),
#        where the API key is, API host if not the site's own)
BOORUS = {
    "danbooru.donmai.us": ("danbooru", "Danbooru", "optional", "https://danbooru.donmai.us/profile", None),
    "safebooru.donmai.us": ("danbooru", "Safebooru (Danbooru)", "optional",
                            "https://safebooru.donmai.us/profile", None),
    "aibooru.online": ("danbooru", "AIBooru", "optional", "https://aibooru.online/profile", None),
    "e621.net": ("e621", "e621", "recommended", "https://e621.net/users/home", None),
    # e926 is e621 with rating:s forced -- and answers Python with a Cloudflare
    # challenge where e621.net does not: asked through e621's API.
    "e926.net": ("e621", "e926", None, None, "e621.net"),
    "gelbooru.com": ("gelbooru", "Gelbooru", "required",
                     "https://gelbooru.com/index.php?page=account&s=options", None),
    "rule34.xxx": ("gelbooru", "Rule 34", "required",
                   "https://rule34.xxx/index.php?page=account&s=options", "api.rule34.xxx"),
    "safebooru.org": ("gelbooru", "Safebooru", None, None, None),
    "xbooru.com": ("gelbooru", "Xbooru", None, None, None),
    "tbib.org": ("gelbooru", "TBIB", None, None, None),
    "hypnohub.net": ("gelbooru", "Hypnohub", None, None, None),
    # Moebooru shows logged-out visitors everything a login would: no logins.
    "yande.re": ("moebooru", "yande.re", None, None, None),
    "konachan.com": ("moebooru", "Konachan", None, None, None),
    "konachan.net": ("moebooru", "Konachan (safe)", None, None, None),
    "sakugabooru.com": ("moebooru", "Sakugabooru", None, None, "www.sakugabooru.com"),   # bare: a 301
}
# Mirrors that share their posts' ids and files with another site: keyed as
# that site, so the same post is one file whichever of them a card lists.
SAME_POSTS = {"konachan.net": "konachan.com", "e926.net": "e621.net",
              "safebooru.donmai.us": "danbooru.donmai.us"}
LOGIN_SITES = [{"host": h, "name": b[1]} for h, b in BOORUS.items() if b[2]]
_WHY = {"required": "%s answers its API only to an account's API key.",
        "recommended": "Logged out, %s leaves out the files of some posts."}
PAGE = {"danbooru": 200, "e621": 320, "gelbooru": 100, "moebooru": 100}
# e621's artist category also holds notes about the post, not people.
_NOT_ARTISTS = {"conditional_dnp", "sound_warning", "unknown_artist", "anonymous_artist", "third-party_edit",
                "avoid_posting", "epilepsy_warning", "unknown_artist_signature"}
# Danbooru's artist tags often carry a qualifier: kantoku_(artist).
_QUALIFIER = re.compile(r"_\((?:artist|cosplayer)\)$")


def _host(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _site(url):
    """(host, engine) of a booru link; unknown hosts by the shape of the link."""
    host, parts = _host(url), urllib.parse.urlparse(url)
    if host in BOORUS:
        return host, BOORUS[host][0]
    query = urllib.parse.parse_qs(parts.query)
    if parts.path.endswith("/index.php") and query.get("page") == ["post"]:
        return host, "gelbooru"
    if parts.path.rstrip("/") == "/posts" and "tags" in query:
        return host, "danbooru"
    if parts.path.rstrip("/") == "/post" and "tags" in query:
        return host, "moebooru"
    return host, None


def match(url):
    host, engine = _site(url.strip())
    if not engine:
        return False
    path, query = urllib.parse.urlparse(url.strip()).path.rstrip("/"), _query(url)
    if engine in ("danbooru", "e621"):
        return (path == "/posts" and bool(query.get("tags"))) or \
            bool(re.fullmatch(r"/(?:posts|artists)/[^/]+", path))
    if engine == "gelbooru":
        return path.endswith("/index.php") and query.get("page") == "post" and \
            bool(query.get("tags") or (query.get("s") == "view" and query.get("id")))
    return path == "/post" and bool(query.get("tags"))


def _query(url):
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}


def _tags(url):
    # order: would replace the newest-first order the cursor walks along.
    return " ".join(t for t in (_query(url).get("tags") or "").split() if not t.lower().startswith("order:"))


def _search_url(host, engine, tags):
    q = urllib.parse.quote_plus(tags, safe=":()")
    if engine in ("danbooru", "e621"):
        return "https://%s/posts?tags=%s" % (host, q)
    if engine == "gelbooru":
        return "https://%s/index.php?page=post&s=list&tags=%s" % (host, q)
    return "https://%s/post?tags=%s" % (host, q)


def normalize(url):
    """The tag search behind a link: an artist's page or a post becomes its artist's tag."""
    url = url.strip()
    host, engine = _site(url)
    path = urllib.parse.urlparse(url).path.rstrip("/")
    tags = _tags(url)
    m = re.fullmatch(r"/(posts|artists)/([^/]+)", path) if engine in ("danbooru", "e621") else None
    if m and not tags:
        tags = _artist_tag(host, engine, m.group(1), urllib.parse.unquote(m.group(2)))
    if not tags:
        raise ValueError("Paste the artist's tag search from %s" % host)
    return _search_url(host, engine, tags)


def _artist_tag(host, engine, what, ref):
    api = "https://%s/" % host
    if what == "artists":
        if not ref.isdigit():
            return ref
        return net.get_json(api + "artists/%s.json" % ref, headers=_auth_headers(host))["name"]
    post = net.get_json(api + "posts/%s.json" % ref, headers=_auth_headers(host))
    if engine == "e621":
        post = post.get("post") or post
        artists = [t for t in (post.get("tags") or {}).get("artist") or [] if t not in _NOT_ARTISTS]
    else:
        artists = (post.get("tag_string_artist") or "").split()
    if not artists:
        raise ValueError("That post names no artist; paste the artist's tag search instead")
    return artists[0]


# ---- logins ----------------------------------------------------------------------------

def account_key(url):
    host, engine = _site(url)
    return "booru:" + host if host in BOORUS and BOORUS[host][2] else None


def account_key_for_host(text):
    host = _host(text if "://" in text else "https://" + text.strip())
    if host not in BOORUS or not BOORUS[host][2]:
        raise ValueError(host)
    return "booru:" + host


def login_need(url):
    host, _engine = _site(url)
    need = BOORUS.get(host, (None, host, None))[2]
    if need not in _WHY:
        return None, ""
    return need, _WHY[need] % BOORUS[host][1]


def login_help(key):
    """What Settings shows next to a booru's login fields."""
    host = key.split(":", 1)[1]
    engine, name, need, page, _api = BOORUS[host]
    gel = engine == "gelbooru"
    return {"label": name, "help": page, "need": need,
            "user_label": "User ID" if gel else "User name",
            "key_hint": ("Paste the whole line \"&api_key=...&user_id=...\" from Options > API Access Credentials"
                         if gel else "API key")}


def _secrets(host):
    return accounts.secrets("booru:" + host)


def _auth_headers(host, data=None):
    data = data or _secrets(host)
    if not data or BOORUS[host][0] == "gelbooru":
        return None
    token = base64.b64encode(("%s:%s" % (data["user"], data["api_key"])).encode()).decode()
    return {"Authorization": "Basic " + token}


def _auth_params(host, data=None):
    data = data or _secrets(host)
    if not data or BOORUS.get(host, ("",))[0] != "gelbooru":
        return {}
    return {"api_key": data["api_key"], "user_id": data["user"]}


def login(key, user, api_key):
    """Check a user name (Gelbooru: user id) and API key with the site, then keep them."""
    host = key.split(":", 1)[1]
    engine, name = BOORUS[host][:2]
    who = "user id" if engine == "gelbooru" else "user name"
    user, api_key = user.strip(), api_key.strip()
    if engine == "gelbooru" and "api_key=" in api_key:      # the line from the options page
        q = urllib.parse.parse_qs(api_key.lstrip("&?"))
        api_key = (q.get("api_key") or [""])[0]
        user = (q.get("user_id") or [user])[0]
    if not user or not api_key:
        raise ValueError("Enter your %s and API key." % who)
    if not _check(host, {"user": user, "api_key": api_key}):
        raise ValueError("%s did not accept this %s and API key." % (name, who))
    accounts.save_token(key, "API key", user=user, api_key=api_key)


def still_logged_in(key):
    host = key.split(":", 1)[1]
    return _check(host, _secrets(host))


def _check(host, data):
    """Whether the site takes these credentials -- asked so that a wrong key fails."""
    engine = BOORUS[host][0]
    try:
        if engine in ("danbooru", "e621"):     # a guest is a user without id; a wrong key is a 401
            return net.get_json("https://%s/%s.json" % (host, "profile" if engine == "danbooru" else "users/me"),
                                headers=_auth_headers(host, data)).get("id") is not None
        _gelbooru(host, "", 0, 1, data)
        return True
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code == 403 and engine == "danbooru":
            raise ValueError("Danbooru took the key, but it may not read your profile: create one "
                             "without permissions or an IP list.") from e
        if code in (401, 403):
            return False
        raise
    except LookupError:                                  # "Missing authentication"
        return False


# ---- listing ---------------------------------------------------------------------------

def profile(url):
    """The artist as the tag names them, once the tag shows at least one post."""
    host, engine = _site(url)
    tags = _tags(url)
    first = next(iter(_posts(host, engine, tags, None, 1)), None)
    if first is None:
        raise RuntimeError("nothing tagged %s on %s" % (tags, host))
    name = _QUALIFIER.sub("", tags.split()[0]).replace("_", " ")
    return {"name": name, "handle": "%s on %s" % (tags, BOORUS.get(host, (None, host))[1]), "avatar": ""}


def pages(url):
    from . import LoginRequired
    host, engine = _site(url)
    tags, before = _tags(url), None
    if login_need(url)[0] == "required" and not _secrets(host):
        raise LoginRequired("%s needs an API key" % host)
    while True:
        try:
            posts = _posts(host, engine, tags, before, PAGE[engine])
        except LookupError as e:
            raise LoginRequired(str(e)) from e
        if not posts:
            return
        yield [m for m in (_media(host, engine, p) for p in posts) if m]
        before = min(int(p["id"]) for p in posts)


def _posts(host, engine, tags, before, limit):
    """One page of posts, newest first, all with an id below before."""
    if engine in ("danbooru", "e621"):
        api = BOORUS.get(host, (None,) * 5)[4] or host
        params = {"tags": tags + (" rating:s" if host == "e926.net" else ""), "limit": limit,
                  "page": "b%d" % before if before else None}
        if engine == "danbooru":       # only what a file needs: a fifth of the answer
            params["only"] = "id,created_at,md5,file_ext,file_url,large_file_url"
        try:
            data = net.get_json("https://%s/posts.json" % api, params, headers=_auth_headers(host))
        except requests.HTTPError as e:
            # 422: more tags than an account may search for at once (Danbooru: 2).
            if e.response is not None and e.response.status_code == 422:
                raise RuntimeError("%s: %s" % (host, _message(e.response))) from e
            raise
        return (data.get("posts") or []) if isinstance(data, dict) else data
    if before:
        tags = "%s id:<%d" % (tags, before)
    if engine == "gelbooru":
        return _gelbooru(host, tags, 0, limit)
    api = BOORUS.get(host, (None,) * 5)[4] or host
    return net.get_json("https://%s/post.json" % api, {"tags": tags, "limit": limit}) or []


def _gelbooru(host, tags, pid, limit, data=None):
    api = BOORUS.get(host, (None, None, None, None, None))[4] or host
    params = dict({"page": "dapi", "s": "post", "q": "index", "json": 1, "tags": tags,
                   "pid": pid, "limit": limit}, **_auth_params(host, data))
    text, _final = net.get_text("https://%s/index.php" % api, params)
    text = text.strip()
    if not text:                                          # no posts: an empty answer, not []
        return []
    if not text.startswith(("[", "{")):
        # rule34.xxx: "Missing authentication. Go to api.rule34.xxx ..."
        raise LookupError("%s: %s" % (host, html.unescape(re.sub(r"<[^>]+>", " ", text))[:120].strip()))
    data = json.loads(text)
    if isinstance(data, dict):                            # gelbooru.com: {"@attributes": ..., "post": [...]}
        data = data.get("post") or []
    return [data] if isinstance(data, dict) else data


def _message(resp):
    try:
        return resp.json().get("message") or resp.reason
    except Exception:
        return resp.reason


def _media(host, engine, p):
    from . import Media
    if engine == "e621":
        f = p.get("file") or {}
        src, ext = f.get("url"), f.get("ext") or ""
    else:
        src, ext = p.get("file_url"), p.get("file_ext") or ""
        if engine == "danbooru" and ext == "zip":         # an ugoira's frames; the WebM is the animation
            src = p.get("large_file_url") or src
    if not src and p.get("directory") and p.get("image"):     # tbib's JSON names no file_url
        src = "/images/%s/%s" % (p["directory"], p["image"])
    if not src:                                           # hidden from this account, or deleted
        return None
    src = urllib.parse.urljoin("https://%s/" % host, src)
    # rule34.xxx's api-cdn sometimes answers with a hotlink page; its images
    # come from wimg. (gallery-dl does the same).
    if "//api-cdn.rule34.xxx/" in src and not src.lower().endswith((".mp4", ".webm")):
        src = src.replace("//api-cdn.rule34.xxx/", "//wimg.rule34.xxx/")
    post = (_search_url(host, engine, "").split("?")[0] + "/%s" % p["id"]) if engine != "gelbooru" else \
        "https://%s/index.php?page=post&s=view&id=%s" % (host, p["id"])
    if engine == "moebooru":
        post = "https://%s/post/show/%s" % (host, p["id"])
    name = urllib.parse.unquote(src.rsplit("/", 1)[-1].split("?")[0])
    same = SAME_POSTS.get(host, host)
    if engine == "moebooru":                              # "yande.re 1198217 every tag of the post.jpg"
        name = "%s %s%s" % (same, p["id"], name[name.rfind("."):] if "." in name else "")
    return Media(remote_key="booru:%s:%s" % (same, p["id"]), url=src, post_url=post,
                 posted=_date(p.get("created_at") or p.get("change")), name=str(p["id"]), filename=name,
                 # Gelbooru's file hosts want to know the page a file is linked from.
                 headers={"Referer": "https://%s/" % host} if engine == "gelbooru" else None)


def _date(value):
    """ISO date from what the engines send: ISO text, a Unix time, or
    Gelbooru's "Sat Oct 10 18:12:27 -0500 2026"."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) or str(value).isdigit():
        return datetime.datetime.fromtimestamp(int(value), datetime.timezone.utc).isoformat()
    try:
        return datetime.datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y").isoformat()
    except ValueError:
        return str(value)
