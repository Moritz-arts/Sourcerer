"""Logins, one file per account in Userdata/Accounts/, mode 600.

Four ways in, whichever the site offers:

  window    the site's own login page in a window of Sourcerer's (pywebview);
            once the site has set the cookie that proves a login, its cookies
            are kept and the window closes by itself. X, Patreon, Pixiv, Fanbox,
            Fantia and XenForo forums ("xenforo:<host>"). Without a window (browser
            mode) a cookies.txt, exported from the browser, does the same.
  oauth     Mastodon ("mastodon:<server>"): the server's own "Authorize
            Sourcerer" page in that window; it hands out a read-only token.
            Misskey ("misskey:<server>") the same with its MiAuth page, whose
            answer Sourcerer asks for itself while the window is open.
  password  Bluesky: the handle and an app password, which Bluesky makes for
            exactly this -- a password that can only be used by apps and can
            be revoked on its own. Kept is the session it opens, not the password.
  api_key   boorus ("booru:<host>"): the user name and the API key the
            site shows in its account settings.

Sourcerer never sees an account's real password. The files never leave the
machine and are never logged; Log out deletes them. Cookies go with every
request to the site's hosts (net.py); tokens and keys are added by the site's
own module to its API requests only.

A login can run out. Every sync that uses one, a check at every start and one
every few hours (sync.check_accounts) mark it "ok" or "expired"; an expired
one is shown as a warning until the user logs in again.

Forums behind Cloudflare's bot check let only a browser through. The login
window is one: the pass it earns (cf_clearance) is saved with its cookies,
and with it the window's User-Agent, which the pass is bound to -- requests
to that forum then carry both.
"""
import datetime
import json
import logging
import os
import re
import threading
import time
import urllib.parse

from . import config

log = logging.getLogger(__name__)
DIR = config.USERDATA / "Accounts"
LOGIN_MINUTES = 10              # a login window left open longer is given up on

# key: (label, login page, cookie domains, test that a cookie jar holds a login)
SITES = {
    "x": ("X", "https://x.com/i/flow/login", ("x.com", "twitter.com"),
          lambda c: bool(c.get("auth_token") and c.get("ct0"))),
    "patreon": ("Patreon", "https://www.patreon.com/login", ("patreon.com",),
                lambda c: bool(c.get("session_id"))),
    # Guests get a PHPSESSID too; a member's starts with the user id.
    "pixiv": ("Pixiv", "https://accounts.pixiv.net/login", ("pixiv.net",),
              lambda c: bool(re.match(r"\d+_", c.get("PHPSESSID", "")))),
    # Fanbox: pixiv's account, its own session cookie.
    "fanbox": ("Fanbox", "https://www.fanbox.cc/login", ("fanbox.cc",), lambda c: bool(c.get("FANBOXSESSID"))),
    # Fantia hands a visitor a session cookie too: only the page says who is in (_PAGE_SAYS).
    "fantia": ("Fantia", "https://fantia.jp/sessions/signin", ("fantia.jp",), lambda c: False),
}
# What "Add account" offers, in the order the rows are shown: (type, label, how it logs in).
# Bluesky, Pixiv, X and Patreon are one login each; a Mastodon server, a forum or a booru is
# as many as the user has. A site is listed here when Sourcerer can download from it.
TYPES = [("bluesky", "Bluesky", "password"), ("mastodon", "Mastodon", "oauth"), ("misskey", "Misskey", "oauth"),
         ("pixiv", "Pixiv", "window"), ("fanbox", "Fanbox", "window"), ("fantia", "Fantia", "window"),
         ("x", "X (Twitter)", "window"), ("patreon", "Patreon", "window"),
         ("xenforo", "XenForo forum", "window"), ("booru", "Booru", "api_key")]
ORDER = [t[0] for t in TYPES]
GROUPS = {"mastodon": "Mastodon", "misskey": "Misskey", "xenforo": "XenForo", "booru": "Booru"}
# XenForo forums are one account each, keyed "xenforo:<host>". The cookie
# prefix is the forum's choice (xf_ by default); <prefix>user is set by a
# login with "Stay logged in", <prefix>session by every visit, guest or not.
_XF_USER = re.compile(r"^[a-z0-9]*_?user$", re.I)

_lock = threading.Lock()
CHANGED = []                    # callbacks(key, how): "new", "renewed" or "logout"
_pending = {}                   # key -> "waiting" | "done" | "failed: why" | "cancelled"
_bases = {}                     # forum key -> base URL a login window was opened with


def waiting(key):
    return _pending.get(key) == "waiting"


def host_of(url):
    host = (urllib.parse.urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def kind(key):
    """How an account logs in: window, oauth, password or api_key."""
    if key in SITES or key.startswith("xenforo:"):
        return "window"
    if key.startswith(("mastodon:", "misskey:")):
        return "oauth"
    if key == "bluesky":
        return "password"
    if key.startswith("booru:"):
        return "api_key"
    raise KeyError(key)


def careful(key):
    """Whether reading with this login must be done like a person would: a cookie login (pixiv, X, Patreon, a
    forum) is what an account gets banned for. A token or a key (Mastodon, Bluesky, a booru) is an API client with
    published limits: it is paced (net's token lane) but needs no spacing between artists, no reading breaks."""
    try:
        return bool(key) and logged_in(key) and kind(key) == "window"
    except KeyError:
        return False


def label(key):
    if key in SITES:
        return SITES[key][0]
    if key == "bluesky":
        return "Bluesky"
    host = key.split(":", 1)[1]
    if key.startswith("booru:"):
        from .sources import booru               # here: sources import this module
        return booru.BOORUS.get(host, (None, host))[1]
    return host


XF_LOGIN = "/index.php?login/"


def describe(key, base=None):
    """(label, login url, domains, logged-in test) of a window account.

    A forum may live below the root (example.com/community/): its base URL,
    taken from a card's link or typed in, comes before the login route -- the root's
    /login/ is somebody else's page, often a 403 or a 404. The route is `index.php?login/`,
    which every XenForo answers (the friendly /login/ is a rewrite of it, and a forum with a
    guard lets only "/" and "index.php?*" through): the window used to open /login/, show the
    guard's bare 403 for seconds and only then swap it.
    """
    if key in SITES:
        return SITES[key]
    if key.startswith("xenforo:"):
        host = key.split(":", 1)[1]
        base = (base or _bases.get(key) or (load(key) or {}).get("base") or "https://" + host).rstrip("/")
        return (host, base + XF_LOGIN, (host,),
                lambda c: any(_XF_USER.match(n) and v for n, v in c.items()))
    raise KeyError(key)


def forum_base(url):
    """https://host[/path] of the forum a XenForo link belongs to."""
    parts = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    path = re.split(r"/(?:media|members|threads|forums|login|index\.php|account|search|attachments)(?:[/?.]|$)",
                    parts.path, 1)[0]
    return "https://%s%s" % (parts.netloc.lower(), path.rstrip("/"))


def key_for(url):
    """The cookie account a URL's host belongs to, or None."""
    host = host_of(url)
    for key, (_label, _login, domains, _ok) in SITES.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return key
    return None


def _path(key):
    return DIR / (re.sub(r"[^a-z0-9.-]+", "_", key.lower()) + ".json")


def load(key):
    try:
        return json.loads(_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _theirs(cookies, domains):
    """The cookies of these domains and their subdomains -- not evil-x.com's for x.com."""
    def ok(c):
        dom = c["domain"].lstrip(".").lower()
        return any(dom == d or dom.endswith("." + d) for d in domains)
    return [c for c in cookies if ok(c)]


def save(key, cookies, how, **extra):
    """cookies: [{name, value, domain, path, expires}] -- only those of the site's domains.
    extra: ua (the login window's User-Agent), base (a forum's base URL)."""
    domains = describe(key, extra.get("base"))[2]
    keep = _theirs(cookies, domains)
    data = dict(extra, key=key, saved=_now(), how=how, cookies=keep, state="ok", checked=_now(), why="")
    first = not _path(key).exists()
    with _lock:
        _write(key, data)
    log.info("%s: login saved (%d cookies, %s)", key, len(keep), how)
    _changed(key, "new" if first else "renewed")
    return data


def save_token(key, how, **secrets):
    """An oauth, password or api_key login: what the site handed out, and who it is (user)."""
    data = dict(secrets, key=key, saved=_now(), how=how, state="ok", checked=_now(), why="")
    first = not _path(key).exists()
    with _lock:
        _write(key, data)
    log.info("%s: login saved (%s)", key, how)
    _changed(key, "new" if first else "renewed")
    return data


def update(key, **fields):
    """Fields of a saved login that change while it is used (a renewed session)."""
    with _lock:
        data = load(key)
        if data:
            data.update(fields)
            _write(key, data)


def _changed(key, how):
    for fn in CHANGED:
        try:
            fn(key, how)
        except Exception:
            log.exception("after the login of %s changed", key)


def _write(key, data):
    DIR.mkdir(parents=True, exist_ok=True)
    path = _path(key)
    tmp = path.with_suffix(".tmp")
    # Readable by this user only, from the first byte on.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def saved(key):
    """When the login on disk was made: what a check judges is that one."""
    return (load(key) or {}).get("saved")


def mark(key, ok, why="", stamp=None):
    """What the last use or check of a login found: still valid, or run out.
    stamp: saved() of the login that was used -- a new login made while the
    request was under way is not the one that failed."""
    with _lock:
        data = load(key)
        if not data or (stamp and data.get("saved") != stamp):
            return
        was = data.get("state")
        data.update(state="ok" if ok else "expired", why="" if ok else why, checked=_now())
        _write(key, data)
    if was != data["state"]:
        log.info("%s: login %s%s", key, data["state"], (" (%s)" % why) if why else "")


def problems(rows=None):
    """The logins that ran out: [{key, label, why}], for the warning in the window.
    rows: accounts() when the caller has it already."""
    return [{"key": a["key"], "label": a["label"], "why": a["why"]}
            for a in (accounts() if rows is None else rows) if a["state"] == "expired"]


def logout(key):
    _path(key).unlink(missing_ok=True)
    _pending.pop(key, None)             # also a login that failed or was given up on: its row goes
    log.info("%s: logged out", key)
    _changed(key, "logout")


def jar(key, fresh=False):
    """The saved cookies of an account as {name: value}, empty when not logged in.
    fresh: only those that may still go out (_fresh) -- what gallery-dl is given."""
    data = load(key)
    return {c["name"]: c["value"] for c in data.get("cookies") or [] if not fresh or _fresh(c)} if data else {}


def logged_in(key):
    data = load(key)
    if not data:
        return False
    try:
        how = kind(key)
    except KeyError:
        return False
    if how == "oauth":
        return bool(data.get("token"))
    if how == "password":
        return bool(data.get("refresh"))
    if how == "api_key":
        return bool(data.get("user") and data.get("api_key"))
    # A forum login without "Stay logged in" sets no <prefix>user cookie;
    # the login window saw the page say so instead (page_login).
    return describe(key)[3](jar(key)) or bool(data.get("page_login"))


def account_for(url):
    """The key of the saved cookie login a request to url would use, or None."""
    host = host_of(url)
    if not host:
        return None
    key = key_for(url)
    if key:
        return key
    return "xenforo:" + host if _path("xenforo:" + host).exists() else None


def headers_for(url):
    """What a request to url carries for a cookie login: its cookies, and for
    a forum whose Cloudflare pass is bound to the login window, that window's
    User-Agent. The big sites' APIs get Sourcerer's own."""
    key = account_for(url)
    if not key:
        return {}
    data = load(key) or {}
    cookies = {c["name"]: c["value"] for c in data.get("cookies") or [] if _fresh(c)}
    out = {"Cookie": "; ".join("%s=%s" % kv for kv in cookies.items())} if cookies else {}
    if key.startswith("xenforo:") and data.get("ua") and "cf_clearance" in cookies:
        out["User-Agent"] = data["ua"]
    return out


# Cookies a bot check sets for minutes (Cloudflare's __cf_bm lives 30): sent
# back days later, they tell the site the session is not a browser's.
_SHORT_LIVED = {"__cf_bm", "_cfuvid", "cf_chl_rc_m", "__cfruid"}


def _fresh(cookie):
    """Whether a saved cookie may still go out: not a bot check's, not expired."""
    if cookie["name"] in _SHORT_LIVED:
        return False
    try:
        expires = float(cookie.get("expires") or 0)
    except ValueError:
        return True                     # a date in another form: the site decides
    return not expires or expires > time.time()


def secrets(key):
    """A token or key login's saved data while it is logged in, else None."""
    return load(key) if logged_in(key) else None


def accounts():
    """Every account there can be: the fixed sites, then each server, forum and booru
    with a login saved or being made (a window open, closed too early, failed) -- that one
    has no file yet. The caller keeps those that are logged in or being logged in."""
    have = list(_pending)
    if DIR.is_dir():
        for p in DIR.glob("*.json"):
            data = load(p.stem) or {}
            if data.get("key"):
                have.append(data["key"])
    fixed = ["bluesky"] + list(SITES)
    rest = sorted({k for k in have if k not in fixed and _known(k)})
    out = []
    for key in sorted(fixed + rest, key=lambda k: (ORDER.index(k.split(":", 1)[0]), k)):
        data = load(key) or {}
        is_in = logged_in(key)
        group = key.split(":", 1)[0]
        out.append({"key": key, "label": label(key), "kind": kind(key), "group": GROUPS.get(group, ""),
                    "logged_in": is_in, "saved": data.get("saved", ""), "how": data.get("how", ""),
                    "pending": _pending.get(key, ""), "state": data.get("state", "") if is_in else "",
                    "why": data.get("why", ""), "checked": data.get("checked", ""),
                    "base": data.get("base", ""), "user": data.get("user", "") if is_in else ""})
    return out


def _known(key):
    try:
        kind(key)
        return True
    except KeyError:
        return False


# ---- logging in in a window --------------------------------------------------------

def login_in_window(key, base=None, url=None, finish=None, ask=None):
    """Open a login page in a window of its own and wait, in the background,
    for the login to show. Returns at once.

    Cookie logins wait for the cookie that proves one. An oauth login passes
    url (the server's authorize page) and finish(code): the window waits for
    the page that shows the code, and finish turns it into the saved login.
    ask(window) says where the answer is instead (Misskey's MiAuth has none on
    the page: Sourcerer asks the server): it returns what finish takes, or None.
    """
    import webview
    if base and key.startswith("xenforo:"):
        _bases[key] = base.rstrip("/")
    if finish:
        title, ok = label(key), None
    else:
        title, url, _domains, ok = describe(key, base)
    with _lock:
        if _pending.get(key) == "waiting":
            return
        _pending[key] = "waiting"
    window = webview.create_window("Log in to %s - Sourcerer" % title, url, width=520, height=760)
    closed = threading.Event()
    window.events.closed += closed.set
    extra = {"base": url[:-len(XF_LOGIN)]} if key.startswith("xenforo:") else {}
    threading.Thread(target=_watch, args=(key, window, ok, closed, extra, finish, ask),
                     daemon=True, name="login-" + key).start()


# Logins a cookie does not prove (a visitor has a session cookie too): what the open page says.
# XenForo 2 marks every page <html data-logged-in="true"> -- and without "Stay logged in" no
# <prefix>user cookie is set. Fantia marks the body with who looks: data-user-type="visitor".
_PAGE_SAYS = {
    "xenforo:": "document.documentElement.getAttribute('data-logged-in') === 'true'",
    "fantia": "!!document.body && !!document.body.getAttribute('data-user-type') && "
              "document.body.getAttribute('data-user-type') !== 'visitor'",
}


def _page_says_logged_in(key, window):
    script = next((js for prefix, js in _PAGE_SAYS.items() if key.startswith(prefix)), None)
    try:
        return bool(script) and window.evaluate_js(script) is True
    except Exception:
        return False


def _window_says_403(window):
    """Whether the window shows a bare 403 page (nginx's: a title and one line, no forum). A forum with a
    guard that lets only "/" and "index.php?*" through answers the friendly /login/ so (the login opens at
    index.php?login/ now and falls back to /login/ when that shows a 403)."""
    try:
        text = window.evaluate_js("(document.title || '') + ' ' + (document.body ? document.body.innerText : '')") or ""
    except Exception:
        return False
    return len(text.strip()) < 300 and "403" in text and "forbidden" in text.lower()


def _oauth_code(window, host):
    """The code the server's authorize page hands out once the user said yes:
    Mastodon puts it in the address (/oauth/authorize/native?code=...), as
    GoToSocial does (/oauth/oob), Pleroma and Akkoma on the page ("Token
    code is ..."). Other pages' codes -- a sign-in provider's callback -- are not it."""
    try:
        parts = urllib.parse.urlparse(window.get_current_url() or "")
    except Exception:
        return None
    if (parts.hostname or "").lower() != host or "oauth" not in parts.path:
        return None
    if parts.path.rstrip("/") in ("/oauth/authorize/native", "/oauth/oob"):
        return (urllib.parse.parse_qs(parts.query).get("code") or [None])[0]
    try:
        text = window.evaluate_js("document.body ? document.body.innerText : ''") or ""
    except Exception:
        return None
    m = re.search(r"Token code is\s*([\w-]{8,})", text)
    return m.group(1) if m else None


def _watch(key, window, ok, closed, extra, finish, ask=None):
    deadline = time.monotonic() + LOGIN_MINUTES * 60
    found = code = at = None
    rerouted = not (key.startswith("xenforo:") and extra.get("base"))      # a forum's login page is tried by its other route once
    while not closed.is_set() and time.monotonic() < deadline:
        time.sleep(1.5 if rerouted else 0.4)         # a bare 403 is swapped quickly: the window shows it meanwhile
        try:        # where the window is, for the log: a forum's 403 page has no address bar to read
            here = urllib.parse.urlparse(window.get_current_url() or "")
            here = here.netloc + here.path          # never the query: an oauth code sits there
        except Exception:
            here = at
        if here != at:
            at = here
            log.info("%s: login window at %s", key, at)
        if not rerouted and _window_says_403(window):
            rerouted = True              # once: a forum that is really down must not be asked in a loop
            log.info("%s: the login page answered 403, trying it as /login/", key)
            try:
                window.load_url(extra["base"] + "/login/")
            except Exception as e:
                log.info("%s: login page not reloaded: %s", key, e)
            continue
        if finish:
            code = ask(window) if ask else _oauth_code(window, key.split(":", 1)[1])
            if code:
                break
            continue
        try:
            cookies = _window_cookies(window)
        except Exception as e:           # the window was closed between two looks
            log.info("%s: cookies not readable (%s)", key, e)
            continue
        if ok({c["name"]: c["value"] for c in cookies}):
            found = cookies
            break
        if _page_says_logged_in(key, window):
            found, extra["page_login"] = cookies, True
            break
    if code:
        try:
            finish(code)
            _pending[key] = "done"
        except Exception as e:
            log.info("%s: login not finished: %s", key, e)
            _pending[key] = "failed: %s" % e
    elif found:
        try:
            extra["ua"] = window.evaluate_js("navigator.userAgent") or ""
        except Exception:
            pass
        save(key, found, "login window", **extra)
        _pending[key] = "done"
    else:
        _pending[key] = "cancelled" if closed.is_set() else "failed: no login within %d minutes" % LOGIN_MINUTES
    if not closed.is_set():
        try:
            window.destroy()
        except Exception:
            pass


def _window_cookies(window):
    """pywebview's cookies (SimpleCookie objects, the current page's) as plain dicts."""
    out = []
    for jar_ in window.get_cookies() or []:
        for name, morsel in jar_.items():
            out.append({"name": name, "value": morsel.value, "domain": morsel["domain"] or "",
                        "path": morsel["path"] or "/", "expires": str(morsel["expires"] or "")})
    return out


# ---- importing a cookies.txt ------------------------------------------------------

def import_cookies_txt(key, text):
    """A Netscape cookies.txt, as browser extensions export it. Returns the
    number of cookies kept; raises ValueError when it holds no login."""
    cookies = []
    for line in text.splitlines():
        if line.startswith("#HttpOnly_"):          # a marker, not a comment
            line = line[len("#HttpOnly_"):]
        parts = line.rstrip("\r").split("\t")
        if line.startswith("#") or len(parts) < 7:
            continue
        domain, _subdomains, path, _secure, expires, name, value = parts[:7]
        cookies.append({"name": name, "value": value, "domain": domain, "path": path, "expires": expires})
    name, _url, domains, ok = describe(key)
    mine = _theirs(cookies, domains)
    if not ok({c["name"]: c["value"] for c in mine}):
        raise ValueError("This file holds no login for %s." % name)
    return len(save(key, mine, "cookies.txt")["cookies"])
