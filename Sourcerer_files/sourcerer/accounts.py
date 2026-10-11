"""Logins: the session cookies of sites that show everything only to members.

A login happens in a window of Sourcerer's own (pywebview), at the site's own
login page -- Sourcerer never sees a password. Once the site has set the cookie
that proves a login, that site's cookies are saved to Userdata/Accounts/ and
the window closes by itself. Without a window (browser mode) a cookies.txt,
exported from the browser with an extension, can be imported instead.

The files never leave the machine and are never logged; Log out deletes them.
net.py attaches them to every request to the site's hosts.
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
}
# XenForo forums are one account each, keyed "xenforo:<host>". The cookie
# prefix is the forum's choice (xf_ by default); <prefix>user is set by a
# login with "Stay logged in", <prefix>session by every visit, guest or not.
_XF_USER = re.compile(r"^[a-z0-9]*_?user$", re.I)

_lock = threading.Lock()
_pending = {}                   # key -> "waiting" | "done" | "failed: why" | "cancelled"


def host_of(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def describe(key):
    """(label, login url, domains, logged-in test) of an account key."""
    if key in SITES:
        return SITES[key]
    if key.startswith("xenforo:"):
        host = key.split(":", 1)[1]
        return (host, "https://%s/login/" % host, (host,),
                lambda c: any(_XF_USER.match(n) and v for n, v in c.items()))
    raise KeyError(key)


def key_for(url):
    """The account a source URL would use, or None."""
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


def save(key, cookies, how):
    """cookies: [{name, value, domain, path, expires}] -- only those of the site's domains."""
    domains = describe(key)[2]
    keep = [c for c in cookies if any(c["domain"].lstrip(".").endswith(d) for d in domains)]
    DIR.mkdir(parents=True, exist_ok=True)
    path = _path(key)
    data = {"key": key, "saved": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "how": how, "cookies": keep}
    tmp = path.with_suffix(".tmp")
    # Readable by this user only, from the first byte on.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)
    log.info("%s: login saved (%d cookies, %s)", key, len(keep), how)
    return data


def logout(key):
    _path(key).unlink(missing_ok=True)
    log.info("%s: logged out", key)


def jar(key):
    """The saved cookies of an account as {name: value}, empty when not logged in."""
    data = load(key)
    return {c["name"]: c["value"] for c in data["cookies"]} if data else {}


def logged_in(key):
    try:
        return bool(describe(key)[3](jar(key)))
    except KeyError:
        return False


def cookies_for(url):
    """{name: value} to send with a request to url: the cookies of the account
    whose domains cover its host. The forums' accounts are looked up by host."""
    host = host_of(url)
    if not host:
        return {}
    key = key_for(url)
    if key:
        return jar(key)
    if _path("xenforo:" + host).exists():
        return jar("xenforo:" + host)
    return {}


def accounts(xenforo_hosts=()):
    """Every account Settings shows: the fixed sites, then each forum a card uses."""
    keys = list(SITES) + ["xenforo:" + h for h in sorted(set(xenforo_hosts))]
    keys += sorted(p.stem.replace("_", ":", 1) for p in DIR.glob("xenforo_*.json")
                   if p.stem.replace("_", ":", 1) not in keys) if DIR.is_dir() else []
    out = []
    for key in keys:
        label, login, _domains, _ok = describe(key)
        data = load(key)
        out.append({"key": key, "label": label, "forum": key.startswith("xenforo:"),
                    "logged_in": logged_in(key), "saved": (data or {}).get("saved", ""),
                    "how": (data or {}).get("how", ""), "pending": _pending.get(key, "")})
    return out


# ---- logging in in a window --------------------------------------------------------

def login_in_window(key):
    """Open the site's login page in a window of its own and wait, in the
    background, for the cookie that proves a login. Returns at once."""
    import webview
    label, url, domains, ok = describe(key)
    with _lock:
        if _pending.get(key) == "waiting":
            return
        _pending[key] = "waiting"
    window = webview.create_window("Log in to %s - Sourcerer" % label, url, width=520, height=760)
    closed = threading.Event()
    window.events.closed += closed.set
    threading.Thread(target=_watch, args=(key, window, domains, ok, closed),
                     daemon=True, name="login-" + key).start()


def _watch(key, window, domains, ok, closed):
    deadline = time.monotonic() + LOGIN_MINUTES * 60
    found = None
    while not closed.is_set() and time.monotonic() < deadline:
        time.sleep(1.5)
        try:
            cookies = _window_cookies(window)
        except Exception as e:           # the window was closed between two looks
            log.info("%s: cookies not readable (%s)", key, e)
            continue
        if ok({c["name"]: c["value"] for c in cookies}):
            found = cookies
            break
    if found:
        save(key, found, "login window")
        _pending[key] = "done"
        try:
            window.destroy()
        except Exception:
            pass
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
    label, _url, domains, ok = describe(key)
    mine = [c for c in cookies if any(c["domain"].lstrip(".").endswith(d) for d in domains)]
    if not ok({c["name"]: c["value"] for c in mine}):
        raise ValueError("This file holds no login for %s." % label)
    return len(save(key, mine, "cookies.txt")["cookies"])
