"""The Flask app the window talks to: a JSON API under /api and the static page.

It listens on 127.0.0.1 only -- nothing here is meant to be reachable from
another machine.
"""
import datetime
import logging
import os
import platform
import random
import re
import subprocess
import sys
import threading
import time
import urllib.parse

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from . import accounts, config, db, gallery, imaging, net, previews, sources, sync, updater

log = logging.getLogger(__name__)
app = Flask(__name__, static_folder=None)
WINDOW = None          # set by desktop.py when a pywebview window is open
URL = ""               # where this server answers, for a second start to open
LAST_SEEN = [time.monotonic()]   # when a page last asked for anything
LAYOUTS = ("together", "per_source")
DEDUPES = ("keep_all", "best", "master")
# What Settings may change, and the values each may take.
CHOICES = {"filenames": ("original", "dated"), "theme": ("system", "light", "dark"),
           "auto_sync": ("0", "1"), "channel": ("stable", "beta")}
RANGES = {"card_size": (160, 800), "auto_hours": (1, 168), "parallel": (1, 16),
          "per_host": (1, 8), "pace_ms": (0, 5000)}


def _background(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def _status(s):
    """What the dot says: ok (green); login or warn (yellow -- it works, with a
    catch: a login, a bot check, a site asking to slow down); error or
    unsupported (red -- nothing comes from it); unknown (grey, not checked yet)."""
    if not s["supported"]:
        return "unsupported"
    if s["last_error"]:
        if s["last_error"].startswith(net.LOGIN_PREFIX):
            return "login"
        return "warn" if s.get("last_level") == "warn" else "error"
    return "ok" if s["last_checked"] else "unknown"


def _artists():
    with db.connect() as con:
        artists = [dict(r) for r in con.execute(
            "SELECT a.*, (SELECT COUNT(*) FROM files f WHERE f.artist_id = a.id "
            "AND f.path IS NOT NULL) AS file_count FROM artists a ORDER BY a.name COLLATE NOCASE")]
        for a in artists:
            a["sources"] = []
            for r in con.execute(
                    "SELECT s.*, (SELECT COUNT(*) FROM files f WHERE f.source_id = s.id "
                    "AND f.path IS NOT NULL) AS file_count FROM sources s WHERE s.artist_id = ? "
                    "ORDER BY s.id", (a["id"],)):
                s = dict(r)
                # Recognised afresh on every read, so better detection reaches
                # sources saved before it (a pixiv link once stored as Mastodon).
                s.update(sources.describe(s["url"]), master=s["id"] == a["master_source_id"])
                s["status"] = _status(s)
                a["sources"].append(s)
            # The newest posts of the card's sources -- with or without a download (previews.py).
            a["thumbs"] = previews.card_thumbs(con, a["id"])
            a["path"] = str(sync.artist_folder(a))
            a["folder"] = a["folder"] or ""
    return artists


def _display_name(name):
    return re.sub(r"\s+", " ", name or "").strip()[:200]


def name_from_url(url):
    """A name when no site says one: the account part of the link."""
    tags = (urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("tags") or [""])[0].split()
    if tags:                                              # a booru's tag search: the first tag
        return re.sub(r"_\((?:artist|cosplayer)\)$", "", tags[0]).replace("_", " ")
    parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    parts = [p for p in parts if p.lower() not in ("profile", "users", "user", "members", "media",
                                                  "c", "u", "en", "gallery", "artworks")]
    name = urllib.parse.unquote(parts[0] if parts else urllib.parse.urlparse(url).hostname or "")
    name = name.lstrip("@").split("@", 1)[0]
    name = re.sub(r"\.bsky\.social$", "", name)
    return re.sub(r"\.\d+$", "", name)                    # XenForo: name.123


def _guess_name(urls):
    """The first source's own display name; failing that, the account in a link."""
    for url in urls:
        try:
            info = sources.profile(url)
            if info and info.get("name"):
                return _display_name(info["name"])
        except Exception as e:
            log.info("no name from %s: %s", url, net.reason(e))
    return _display_name(name_from_url(urls[0])) if urls else ""


def _clean(body):
    urls = []
    for url in body.get("sources") or []:
        url = sources.normalize(url)
        # Compared after normalising: "site/@a/media" and "https://site/@a" are one.
        if url and url not in urls:
            urls.append(url)
    name = _display_name(body.get("name")) or _guess_name(urls)
    if not name:
        return None, "Give the card a name or at least one link."
    folder = (body.get("folder") or "").strip()
    if folder:
        folder = os.path.abspath(os.path.expanduser(folder))
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            return None, "This folder cannot be used: %s" % e
    return {"name": name, "urls": urls, "master": sources.normalize(body.get("master") or ""),
            "folder": folder or None,
            "layout": body.get("layout") if body.get("layout") in LAYOUTS else "together",
            "dedupe": body.get("dedupe") if body.get("dedupe") in DEDUPES else "best"}, None


def _save(con, artist_id, data):
    """Keep the sources still listed (with their history), add new, drop the rest."""
    current = {r["url"]: r["id"] for r in con.execute(
        "SELECT id, url FROM sources WHERE artist_id = ?", (artist_id,))}
    for url, sid in current.items():
        if url not in data["urls"]:
            con.execute("DELETE FROM sources WHERE id = ?", (sid,))
    for url in data["urls"]:
        if url not in current:
            con.execute("INSERT INTO sources (artist_id, url, kind) VALUES (?, ?, ?)",
                        (artist_id, url, sources.kind_of(url)))
    master = con.execute("SELECT id FROM sources WHERE artist_id = ? AND url = ?",
                         (artist_id, data["master"])).fetchone()
    con.execute("UPDATE artists SET name = ?, layout = ?, dedupe = ?, master_source_id = ?, "
                "folder = ? WHERE id = ?", (data["name"], data["layout"], data["dedupe"],
                                            master[0] if master else None, data["folder"], artist_id))


def _open(path):
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


def _shutdown():
    """Close Sourcerer so the update helper can take over."""
    def run():
        time.sleep(0.8)                         # the answer reaches the page first
        if WINDOW is not None:
            try:
                WINDOW.destroy()
                time.sleep(3)             # main() returns once the window is gone
            except Exception:
                pass
        os._exit(0)
    _background(run)


# ---- page --------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(config.STATIC, "index.html")


@app.get("/static/<path:name>")
def static_file(name):
    return send_from_directory(config.STATIC, name)


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(config.STATIC, "logo.svg", mimetype="image/svg+xml")


@app.before_request
def _seen():
    LAST_SEEN[0] = time.monotonic()


_LOCAL = ("127.0.0.1", "localhost")


@app.before_request
def _same_origin():
    """Only Sourcerer's own page may change anything. Any web page in the
    user's browser could otherwise POST to 127.0.0.1 -- a form needs no
    permission -- and log accounts in or out, or start syncs. A page from
    elsewhere names itself in Origin; a renamed host (DNS rebinding) shows in Host."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    host = urllib.parse.urlsplit("//" + (request.host or ""))
    origin = request.headers.get("Origin")
    seen = urllib.parse.urlsplit(origin) if origin else None
    if host.hostname not in _LOCAL or (seen is not None and (
            seen.hostname not in _LOCAL or seen.port != host.port)):
        abort(403)
    return None


@app.get("/api/ping")
def ping():
    return jsonify(app="sourcerer", version=config.VERSION, pid=os.getpid())


@app.post("/api/focus")
def focus():
    """A second start of Sourcerer asks this one to come forward instead."""
    if WINDOW is not None:
        try:
            WINDOW.restore()
            WINDOW.show()
            WINDOW.on_top = True          # the only way past Windows' focus-stealing guard
            WINDOW.on_top = False
        except Exception as e:
            log.info("could not bring the window forward: %s", e)
    else:
        import webbrowser
        webbrowser.open(URL)
    return jsonify(ok=True)


@app.post("/api/quit")
def quit_app():
    _shutdown()
    return jsonify(ok=True)


@app.get("/api/state")
def state():
    rows = accounts.accounts()
    # The card dialog lists the sites with a saved login (even one that ran out:
    # the link then says so) -- a site is its accounts' key before the colon.
    have = {a["key"].split(":", 1)[0] for a in rows if a["logged_in"] and _shown(a["key"])}
    on = {s.LABEL: s.KIND in have for s in sources.SITES}
    return jsonify(version=config.VERSION, library=sync.library(), sep=os.sep,
                   sites=[s.LABEL for s in sources.SITES], settings=db.settings(),
                   fields=[{"label": label, "example": example, "logged_in": on.get(label, False)}
                           for label, example in sources.FIELDS],
                   logins=accounts.problems(rows), pauses=net.pauses(),
                   artists=_artists(), sync=sync.status(), window=WINDOW is not None)


# ---- artist cards --------------------------------------------------------------

@app.post("/api/detect")
def detect():
    """What a pasted link is, and whether the account behind it answers."""
    url = sources.normalize((request.get_json(force=True) or {}).get("url"))
    if not url:
        return jsonify(error="That is not a link."), 400
    info = dict(url=url, name=_display_name(name_from_url(url)), **sources.describe(url))
    if not info["supported"]:
        info["status"] = "unsupported"
        return jsonify(info)
    try:
        p = sources.profile(url) or {}
        info.update(status="ok", name=_display_name(p.get("name")) or info["name"],
                    handle=p.get("handle", ""), from_site=bool(p.get("name")) and not p.get("from_link"))
    except Exception as e:
        why = net.reason(e)
        info.update(status="login" if why.startswith(net.LOGIN_PREFIX) else net.level(e), error=why)
    info["account"] = note = _login_note(url, info["status"])
    if note and note["need"] == "required" and info["status"] == "ok":
        # The account is there, but nothing downloads without the login: yellow, not green.
        info.update(status="login", error=note["why"])
    return jsonify(info)


def _login_note(url, status):
    """What the card dialog says under a link about its login, or None.
    need: required -- nothing comes without one; recommended -- part of it
    does not; a login that ran out is said either way."""
    key = sources.account_key(url)
    if not key:
        return None
    need, why = sources.login_need(url)
    if status == "login":
        need, why = "required", why or "This site shows it to logged-in accounts only."
    data = accounts.load(key) or {}
    logged_in = accounts.logged_in(key)
    expired = logged_in and data.get("state") == "expired"
    if (logged_in and not expired) or (not need and not expired):
        return None
    return {"key": key, "label": accounts.label(key), "need": need or "recommended", "why": why,
            "expired": expired, "kind": accounts.kind(key)}


@app.post("/api/artists")
def create_artist():
    body = request.get_json(force=True) or {}
    data, error = _clean(body)
    if error:
        return jsonify(error=error), 400
    with db.connect() as con:
        artist_id = con.execute("INSERT INTO artists (name) VALUES (?)", (data["name"],)).lastrowid
        _save(con, artist_id, data)
    _background(sync.check_card, artist_id)
    previews.soon(artist_id)
    if body.get("sync_now"):
        sync.enqueue([artist_id])
    return jsonify(id=artist_id)


@app.put("/api/artists/<int:artist_id>")
def update_artist(artist_id):
    body = request.get_json(force=True) or {}
    data, error = _clean(body)
    if error:
        return jsonify(error=error), 400
    with db.connect() as con:
        row = con.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        if not row:
            return jsonify(error="This card no longer exists."), 404
        _move_folder(con, artist_id, sync.artist_folder(row),
                     sync.artist_folder(dict(row, name=data["name"], folder=data["folder"])))
        _save(con, artist_id, data)
    sync.name_avatar(artist_id)                  # the picture's file is named after the artist
    _background(sync.check_card, artist_id)
    previews.soon(artist_id)                     # another source may have newer pictures
    if body.get("sync_now"):
        sync.enqueue([artist_id])
    return jsonify(ok=True)


def _move_folder(con, artist_id, src, dst):
    """The folder follows the card -- renamed or moved elsewhere -- so one artist
    never ends up in two folders. Across drives that would mean copying the
    whole collection inside a click; there the new files simply go to dst."""
    if src == dst or not src.is_dir() or dst.exists():
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dst)
    except OSError as e:
        log.info("folder not moved (%s); new files go to %s", e, dst)
        return
    for row in con.execute("SELECT id, path FROM files WHERE artist_id = ? AND path IS NOT NULL",
                           (artist_id,)).fetchall():
        if row["path"].startswith(str(src) + os.sep):
            con.execute("UPDATE files SET path = ? WHERE id = ?",
                        (str(dst) + row["path"][len(str(src)):], row["id"]))


@app.delete("/api/artists/<int:artist_id>")
def delete_artist(artist_id):
    # The files stay on disk: they are the user's now, in the user's library.
    # What Sourcerer knew about them goes to the archive, so a card made again
    # for this artist takes them over instead of downloading them once more.
    sync.cancel(artist_id)
    with db.connect() as con:
        row = con.execute("SELECT avatar FROM artists WHERE id = ?", (artist_id,)).fetchone()
        con.execute("INSERT OR REPLACE INTO archive (remote_key, sha256, path, post_url, posted, "
                    "phash, width, height, size) SELECT remote_key, sha256, path, post_url, posted, "
                    "phash, width, height, size FROM files WHERE artist_id = ? AND path IS NOT NULL",
                    (artist_id,))
        con.execute("DELETE FROM artists WHERE id = ?", (artist_id,))
    if row and row["avatar"]:
        (config.AVATARS / row["avatar"]).unlink(missing_ok=True)
    previews.forget(artist_id)
    return jsonify(ok=True)


@app.get("/api/avatar/<int:artist_id>")
def avatar(artist_id):
    with db.connect() as con:
        row = con.execute("SELECT avatar FROM artists WHERE id = ?", (artist_id,)).fetchone()
    path = config.AVATARS / row["avatar"] if row and row["avatar"] else None
    if not path or not path.is_file():
        abort(404)
    resp = send_file(path, mimetype="image/jpeg")
    resp.cache_control.max_age = 86400          # the page asks with ?v=<when it changed>
    return resp


# ---- syncing -------------------------------------------------------------------

@app.post("/api/sync")
def start_sync():
    body = request.get_json(silent=True) or {}
    ids = [int(body["artist_id"])] if body.get("artist_id") else None
    # sources: only these of the card (Browse: download what the filter shows).
    only = [int(i) for i in body.get("sources") or []] if ids else None
    return jsonify(added=sync.enqueue(ids, only=only))


@app.post("/api/sync/cancel")
def cancel_sync():
    body = request.get_json(silent=True) or {}
    return jsonify(ok=sync.cancel(int(body.get("artist_id") or 0)))


@app.get("/api/sync")
def sync_status():
    return jsonify(dict(sync.status(), pauses=net.pauses(), previews=previews.version))


@app.get("/api/thumb/<int:file_id>")
def thumb(file_id):
    """A downloaded picture, made small in memory -- no thumbnail files on disk."""
    with db.connect() as con:
        row = con.execute("SELECT path FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row or not row["path"] or not os.path.isfile(row["path"]):
        abort(404)
    try:
        data = imaging.preview(row["path"])
    except Exception:
        abort(404)
    resp = app.response_class(data, mimetype="image/jpeg")
    resp.cache_control.max_age = 7 * 86400       # the page asks with ?v=<the file's hash>
    return resp


@app.get("/api/preview/<int:artist_id>/<name>")
def preview(artist_id, name):
    """A card's kept picture of a post that is not downloaded (previews.py). The name is a
    hash made here: nothing else is served from that folder."""
    if not previews.NAME.match(name) or not (previews.folder(artist_id) / name).is_file():
        abort(404)
    resp = send_from_directory(previews.folder(artist_id), name, mimetype="image/jpeg")
    resp.cache_control.max_age = 30 * 86400       # the name is the post's own: it never changes
    return resp


# ---- the gallery -----------------------------------------------------------------------

def _own_page():
    """GETs skip _same_origin. These answer with what the user's logins fetched,
    so a page from elsewhere (Sec-Fetch-Site) or a renamed host gets nothing."""
    host = urllib.parse.urlsplit("//" + (request.host or ""))
    if host.hostname not in _LOCAL or request.headers.get("Sec-Fetch-Site") == "cross-site":
        abort(403)


@app.post("/api/gallery/open")
def gallery_open():
    try:
        # No artist: every card (All artists).
        return jsonify(gallery.open_gallery(int((request.get_json(force=True) or {}).get("artist_id") or 0) or None))
    except KeyError:
        abort(404)


@app.post("/api/gallery/more")
def gallery_more():
    body = request.get_json(force=True) or {}
    try:
        return jsonify(gallery.more(body.get("gallery") or "", body.get("n") or gallery.PAGE, body.get("off")))
    except KeyError:
        return jsonify(error="This gallery was closed; open it again."), 410


@app.get("/api/gallery/<gallery_id>/<int:number>/<size>")
def gallery_picture(gallery_id, number, size):
    _own_page()
    if size not in ("thumb", "large"):
        abort(404)
    try:
        ctype, data = gallery.picture(gallery_id, number, size)
    except KeyError:
        abort(404)
    except Exception as e:
        log.info("gallery picture: %s", net.reason(e))
        abort(502)
    resp = app.response_class(data, mimetype=ctype)
    resp.headers["Cache-Control"] = "no-store"     # in Sourcerer's memory only, not the web view's cache
    return resp


@app.get("/api/gallery/file/<int:file_id>")
def gallery_file(file_id):
    """A downloaded file, whole, for the gallery's large view."""
    _own_page()
    with db.connect() as con:
        row = con.execute("SELECT path FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row or not row["path"] or not os.path.isfile(row["path"]):
        abort(404)
    return send_file(row["path"], conditional=True, max_age=0)


@app.post("/api/gallery/download")
def gallery_download():
    body = request.get_json(force=True) or {}
    try:
        item, kept = gallery.download(body.get("gallery") or "", int(body.get("item") or 0))
        return jsonify(item=item, kept=kept)
    except KeyError:
        return jsonify(error="This gallery was closed; open it again."), 410
    except Exception as e:
        return jsonify(error=net.reason(e)), 502


@app.post("/api/gallery/close")
def gallery_close():
    gallery.close((request.get_json(force=True) or {}).get("gallery") or "")
    return jsonify(ok=True)


@app.post("/api/open-url")
def open_url():
    """A source's page in the system's browser -- not inside Sourcerer's window."""
    url = (request.get_json(force=True) or {}).get("url") or ""
    if not re.match(r"^https?://", url):
        abort(400)
    import webbrowser
    webbrowser.open(url)
    return jsonify(ok=True)


# ---- settings --------------------------------------------------------------------

@app.get("/api/settings")
def get_settings():
    return jsonify(settings=db.settings(), library=sync.library(),
                   default_library=str(config.DEFAULT_LIBRARY))


@app.put("/api/settings")
def save_settings():
    body = request.get_json(force=True) or {}
    clean = {}
    for key, value in body.items():
        value = str(value).strip()
        if key == "library":
            if value:
                value = os.path.abspath(os.path.expanduser(value))
                try:
                    os.makedirs(value, exist_ok=True)
                except OSError as e:
                    return jsonify(error="This folder cannot be used: %s" % e), 400
        elif key in CHOICES:
            if value not in CHOICES[key]:
                return jsonify(error="Unknown value for %s." % key), 400
        elif key in RANGES:
            low, high = RANGES[key]
            if not value.isdigit():
                return jsonify(error="%s must be a number." % key), 400
            value = str(max(low, min(high, int(value))))
        else:
            return jsonify(error="Unknown setting: %s." % key), 400
        clean[key] = value
    for key, value in clean.items():
        if key in ("auto_sync", "auto_hours") and db.get_setting(key) != value:
            db.set_setting("next_auto", "")        # drawn from the old interval: draw anew when due
        db.set_setting(key, value)
    net.configure(per_host=db.setting_int("per_host", 1, 8), pace_ms=db.setting_int("pace_ms", 0, 5000))
    return get_settings()


@app.post("/api/pick-folder")
def pick_folder():
    if WINDOW is None:
        return jsonify(error="Type the path in; the browser cannot show a folder dialog."), 501
    import webview
    start = ((request.get_json(silent=True) or {}).get("start") or "").strip()
    while start and not os.path.isdir(start):          # a folder not made yet: its parent
        parent = os.path.dirname(start.rstrip("\\/"))
        start = parent if parent != start else ""
    # pywebview 6 turned FOLDER_DIALOG into a deprecated function; passing it
    # as the dialog type opens no folder dialog at all. FileDialog is the 6.x way.
    folder = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
    picked = WINDOW.create_file_dialog(folder, directory=start or sync.library())
    return jsonify(path=picked[0] if picked else None)


@app.post("/api/open")
def open_path():
    body = request.get_json(silent=True) or {}
    target = body.get("target")
    if target == "artist":
        with db.connect() as con:
            row = con.execute("SELECT * FROM artists WHERE id = ?",
                              (int(body.get("artist_id") or 0),)).fetchone()
        if not row:
            abort(404)
        path = str(sync.artist_folder(row))
    else:
        path = {"library": sync.library(), "logs": str(config.LOG_DIR),
                "program": str(config.INSTALL), "userdata": str(config.USERDATA),
                "accounts": str(accounts.DIR)}.get(target)
        if not path:
            abort(400)
    try:
        _open(path)
    except OSError:                       # no file manager (a bare Linux): say where the folder is
        return jsonify(error="No file manager found. The folder is: %s" % path), 501
    return jsonify(ok=True)


@app.get("/api/info")
def info():
    try:
        lines = (config.LOG_DIR / "update.log").read_text(encoding="utf-8").splitlines()[-30:]
    except OSError:
        lines = []
    from .sources import _gdl
    return jsonify(version=config.VERSION, python=platform.python_version(), gallery_dl=_gdl.version(),
                   system="%s %s" % (platform.system(), platform.release()),
                   program=str(config.INSTALL), userdata=str(config.USERDATA),
                   library=sync.library(), repo="https://github.com/%s" % config.REPO,
                   update_log=lines, window=WINDOW is not None)


# ---- accounts -----------------------------------------------------------------------

# Sites where a login shows posts a visitor never sees: R-18 works, a patron's
# posts, a forum's members-only media, followers-only posts, a booru's hidden files.
REVEALS = ("pixiv", "patreon", "xenforo:", "mastodon:", "booru:")


def _login_changed(key, how="new"):
    """A first login opens older posts the early stop would never reach again:
    the sources it covers walk their whole history on the next sync. Not after
    a renewed login (the same posts as before) or a logout, and not on X or
    Bluesky, where a login shows nothing more -- a walk there is only risk.
    Any new login also ends a rest the old one's refusals or a bot check began."""
    if how in ("new", "renewed"):
        try:
            net.lift(sync._site_url(key))
        except (KeyError, IndexError):
            pass
    if how != "new" or not key.startswith(REVEALS):
        return
    with db.connect() as con:
        for row in con.execute("SELECT id, url FROM sources").fetchall():
            if sources.account_key(row["url"]) == key:
                con.execute("UPDATE sources SET complete = 0 WHERE id = ?", (row["id"],))


accounts.CHANGED.append(_login_changed)


def _forums():
    """{host: base URL} of every XenForo forum a card links to."""
    with db.connect() as con:
        urls = [r[0] for r in con.execute("SELECT url FROM sources ORDER BY id")]
    out = {}
    for u in urls:
        if sources.describe(u)["label"] == "XenForo":
            out.setdefault(accounts.host_of(u), accounts.forum_base(u))
    return out


def _account_key(body):
    """(key, the forum's base URL or None) of the account a request names:
    by key, or a forum, Mastodon server or booru typed in by hand."""
    key, base = (body.get("key") or "").strip().lower(), None
    if body.get("forum"):                      # a forum: its host is the key
        base = accounts.forum_base(body["forum"].strip())
        key = "xenforo:" + accounts.host_of(base)
    elif body.get("server"):
        from .sources import mastodon
        key = "mastodon:" + mastodon.server_of(body["server"])
    elif body.get("booru"):
        from .sources import booru
        try:
            key = booru.account_key_for_host(body["booru"])
        except ValueError:
            abort(400)
    elif key.startswith("xenforo:"):
        # A forum below the root: its base from the card's links, or from the
        # link the card dialog asks about before the card is saved.
        url = body.get("url") or ""
        base = _forums().get(key.split(":", 1)[1]) or \
            (accounts.forum_base(url) if url and accounts.host_of(url) == key.split(":", 1)[1] else None)
    if not _shown(key):
        abort(400)
    return key, base


def _shown(key):
    """A key Manage Accounts may list: one a site of Sourcerer's would use."""
    from .sources import booru
    try:
        how = accounts.kind(key)
    except KeyError:
        return False
    host = key.split(":", 1)[-1]
    return bool(host) and (how != "api_key" or booru.BOORUS.get(host, (0, 0, None))[2] is not None)


@app.get("/api/accounts")
def get_accounts():
    """The logins there are -- saved ones, and one being made or given up on (a window
    open, a window closed too early) -- and what "Add account" offers. A site without a
    login has no row; it is added from the list of types."""
    from .sources import booru
    rows = [a for a in accounts.accounts() if _shown(a["key"]) and (a["logged_in"] or a["pending"])]
    for a in rows:
        if a["kind"] == "api_key":
            a.update(booru.login_help(a["key"]))
        host = a["key"].split(":", 1)[1] if ":" in a["key"] else (
            accounts.SITES[a["key"]][2][0] if a["key"] in accounts.SITES else "bsky.social")
        if a["key"].startswith("booru:"):
            host = booru.BOORUS.get(host, (0, 0, 0, 0, None))[4] or host       # paused under its API host
        rest = net.paused(host)
        a["rest"] = {"until": rest[0], "why": rest[1]} if rest else None
    boorus = [dict(b, **booru.login_help("booru:" + b["host"])) for b in booru.LOGIN_SITES]
    types = [{"type": t, "label": label, "kind": how, "many": t in ("mastodon", "xenforo", "booru")}
             for t, label, how in accounts.TYPES]
    return jsonify(accounts=rows, types=types, window=WINDOW is not None, boorus=boorus)


@app.post("/api/accounts/login")
def account_login():
    """Log in: a window for cookie and Mastodon logins; the fields for the others."""
    body = request.get_json(force=True) or {}
    key, base = _account_key(body)
    how = accounts.kind(key)
    try:
        if how == "password":
            from .sources import bluesky
            bluesky.login(body.get("handle") or "", body.get("password") or "")
            return jsonify(ok=True, key=key)
        if how == "api_key":
            from .sources import booru
            booru.login(key, body.get("user") or "", body.get("api_key") or "")
            return jsonify(ok=True, key=key)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error="No answer from the site: %s" % net.reason(e)), 502
    if WINDOW is None:
        return jsonify(error="Logging in needs Sourcerer's own window." +
                       (" In the browser, import a cookies.txt instead." if how == "window" else ""),
                       key=key), 501
    if accounts.waiting(key):              # its window is open already
        return jsonify(ok=True, key=key)
    if how == "oauth":
        from .sources import mastodon
        server = key.split(":", 1)[1]
        try:
            url, finish = mastodon.start_login(server)
        except Exception as e:
            return jsonify(error="%s did not let Sourcerer register as an app (%s). "
                                 "Is it a Mastodon server?" % (server, net.reason(e))), 502
        accounts.login_in_window(key, url=url, finish=finish)
    else:
        accounts.login_in_window(key, base)
    return jsonify(ok=True, key=key)


@app.post("/api/accounts/check")
def account_check():
    key, _base = _account_key(request.get_json(force=True) or {})
    sync.check_accounts([key])
    return get_accounts()


@app.post("/api/accounts/logout")
def account_logout():
    """Forget a login -- after asking its site to end it, where the site has a way."""
    key = _account_key(request.get_json(force=True) or {})[0]
    site = next((s for s in sources.SITES if s.KIND == key.split(":", 1)[0]), None)
    if getattr(site, "logout", None):
        site.logout(key)
    accounts.logout(key)
    return jsonify(ok=True)


@app.post("/api/accounts/import")
def account_import():
    body = request.get_json(force=True) or {}
    key, _base = _account_key(body)
    if accounts.kind(key) != "window":
        return jsonify(error="This site logs in another way."), 400
    try:
        n = accounts.import_cookies_txt(key, body.get("text") or "")
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, key=key, cookies=n)


# ---- updates and repair --------------------------------------------------------------

@app.post("/api/update/gallery-dl")
def update_gallery_dl():
    from .sources import _gdl
    try:
        version = _gdl.upgrade()
    except Exception as e:
        return jsonify(error=str(e)), 500
    db.set_setting("gdl_updated", datetime.datetime.now(datetime.timezone.utc).isoformat())
    return jsonify(version=version)


@app.get("/api/update/check")
def update_check():
    channel = request.args.get("channel") or db.get_setting("channel")
    try:
        return jsonify(updater.check("beta" if channel == "beta" else "stable"))
    except Exception as e:
        return jsonify(error="GitHub could not be asked: %s" % net.reason(e)), 502


@app.post("/api/update/install")
def update_install():
    channel = (request.get_json(silent=True) or {}).get("channel") or db.get_setting("channel")
    if sync.status()["running"]:
        return jsonify(error="Wait for the running sync to finish, or cancel it."), 409
    try:
        result = updater.install("beta" if channel == "beta" else "stable")
    except Exception as e:
        log.exception("update failed")
        return jsonify(error=net.reason(e)), 500
    _shutdown()
    return jsonify(result)


@app.post("/api/repair")
def repair():
    action = (request.get_json(silent=True) or {}).get("action")
    if action == "avatars":
        with db.connect() as con:
            ids = [r[0] for r in con.execute("SELECT id FROM artists")]
        def run():                     # one card after another, a few seconds apart, like a sync
            for i in ids:
                sync.check_card(i)
                time.sleep(random.uniform(3, 10))
        _background(run)
        return jsonify(message="Profile pictures and link checks are being refreshed.")
    if action not in ("venv", "reinstall", "restart"):
        abort(400)
    if sync.status()["running"]:
        return jsonify(error="Wait for the running sync to finish, or cancel it."), 409
    try:
        if action == "venv":
            (config.USERDATA / "rebuild-venv").write_text("Settings > Repair\n", encoding="utf-8")
            updater.restart()
        elif action == "reinstall":
            updater.reinstall()
        else:
            updater.restart()
    except Exception as e:
        log.exception("repair failed")
        return jsonify(error=net.reason(e)), 500
    _shutdown()
    return jsonify(message="Sourcerer restarts in a moment.")
