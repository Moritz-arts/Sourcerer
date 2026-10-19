"""The master password, and wiping Sourcerer back to a fresh install.

A master password makes the page ask for it each time Sourcerer is started. It is kept as a salted
PBKDF2 hash in the settings (never the password), and the server enforces it: until somebody has
unlocked, every API call but the few the start needs answers 401 "locked" (`server._locked`). An
unlock is a random token, kept in memory and handed out as a cookie, so a restart locks again and
nothing else on the machine can borrow the unlock by calling the API. Wrong passwords are slowed
down after a few tries.

It keeps other people from using the window; it does not encrypt Userdata -- whoever can read the
files can read the logins. Syncing in the background goes on while it is locked.

`wipe()` is the other half: log out of everything and remove what Sourcerer keeps about the user, so
the next start is a fresh install. The library (the downloaded files) is not touched: it may be
somebody else's folder, and a TrackImage library at that.
"""
import hashlib
import hmac
import logging
import os
import secrets
import shutil
import sqlite3
import threading
import time

from . import accounts, config, db

log = logging.getLogger(__name__)
KEY = "master_hash"            # in the settings table, which /api/settings does not show (not in DEFAULTS)
COOKIE = "sourcerer_unlock"
ITERATIONS = 240_000
MIN_LENGTH = 4
FREE_TRIES = 3                 # wrong passwords before each further one makes the next wait
MAX_WAIT = 300                 # seconds

_lock = threading.Lock()
_tokens = set()
_hash = [None]                 # the stored hash, or "" for none; None: not read yet
_fails = [0]
_until = [0.0]                 # no new try before this (time.monotonic)


class Locked(Exception):
    """Too many wrong passwords: .wait seconds until the next try."""

    def __init__(self, wait):
        super().__init__("Too many tries. Wait %d seconds." % wait)
        self.wait = wait


def _stored():
    if _hash[0] is None:
        _hash[0] = db.get_setting(KEY, "") or ""
    return _hash[0]


def enabled():
    return bool(_stored())


def _make(password, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (ITERATIONS, salt.hex(), digest.hex())


def check(password):
    """Whether password is the master password (no password set: whatever is asked is fine)."""
    stored = _stored()
    if not stored:
        return True
    try:
        _algo, iterations, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(test.hex(), digest)
    except ValueError:
        return False


def _issue():
    token = secrets.token_urlsafe(32)
    with _lock:
        _tokens.add(token)
    return token


def valid(token):
    return bool(token) and token in _tokens


def unlock(password):
    """A token for the cookie, or None for a wrong password; Locked while the tries are used up."""
    with _lock:
        wait = _until[0] - time.monotonic()
        if wait > 0:
            raise Locked(int(wait) + 1)
    if check(password):
        _fails[0] = 0
        return _issue()
    with _lock:
        _fails[0] += 1
        if _fails[0] > FREE_TRIES:
            _until[0] = time.monotonic() + min(MAX_WAIT, 5 * 2 ** (_fails[0] - FREE_TRIES - 1))
    return None


def lock(token):
    with _lock:
        _tokens.discard(token)


def set_password(new, current=""):
    """Set, change (current must be the old one) or, with new empty, remove the password.
    Returns a token for the session that did it -- it must not lock itself out -- or None."""
    if enabled() and not check(current):
        raise ValueError("The current password is not right.")
    new = new or ""
    if new and len(new) < MIN_LENGTH:
        raise ValueError("Use at least %d characters." % MIN_LENGTH)
    db.set_setting(KEY, _make(new) if new else "")
    _hash[0] = None
    with _lock:
        _tokens.clear()                  # a changed password ends every unlock
    return _issue() if new else None


# ---- a fresh install ----------------------------------------------------------------

def _clear_dir(path):
    shutil.rmtree(path, ignore_errors=True)


def _clear_logs():
    """The log files: removed, or -- one that is open (the console log, on Windows) -- emptied."""
    if not config.LOG_DIR.is_dir():
        return
    for p in config.LOG_DIR.iterdir():
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()
        except OSError:
            try:
                open(p, "w").close()
            except OSError as e:
                log.info("log file %s kept: %s", p.name, e)


def wipe():
    """Log out of everything, forget the cards, settings and the master password, remove the caches and
    the logs. Kept: the library, backups and what the updater keeps. Returns the steps, for the answer."""
    from . import sources
    done = []
    for a in accounts.accounts():
        if not a["logged_in"]:
            continue
        site = next((s for s in sources.SITES if s.KIND == a["key"].split(":", 1)[0]), None)
        try:
            if getattr(site, "logout", None):
                site.logout(a["key"])            # the site is told too (Mastodon revokes the token)
        except Exception as e:
            log.info("%s: not logged out on the site: %s", a["key"], e)
        accounts.logout(a["key"])
    _clear_dir(accounts.DIR)                     # whatever file is left of a login
    done.append("logged out")
    con = db.connect()
    try:
        con.execute("PRAGMA foreign_keys = OFF")
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        for name in names:
            con.execute('DELETE FROM "%s"' % name)
        con.commit()
        con.execute("VACUUM")
    except sqlite3.Error:
        con.rollback()
        raise
    finally:
        con.close()
    db.init()
    _hash[0] = None
    with _lock:
        _tokens.clear()
        _fails[0], _until[0] = 0, 0.0
    done.append("cards and settings")
    for path in (config.AVATARS, config.PREVIEWS, config.USERDATA / "gallery-dl"):
        _clear_dir(path)
    _clear_logs()
    done.append("pictures, caches and logs")
    log.info("Sourcerer was reset: %s", ", ".join(done))
    return done
