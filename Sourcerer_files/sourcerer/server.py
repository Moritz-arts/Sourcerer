"""The Flask app the window talks to: a JSON API under /api and the static page.

It listens on 127.0.0.1 only -- nothing here is meant to be reachable from
another machine.
"""
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from . import accounts, config, db, imaging, net, sources, sync, updater

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
RANGES = {"card_size": (160, 420), "auto_hours": (1, 168), "parallel": (1, 16),
          "per_host": (1, 8), "pace_ms": (0, 5000)}


def _background(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def _status(s):
    if not s["supported"]:
        return "unsupported"
    if s["last_error"]:
        return "login" if s["last_error"].startswith(net.LOGIN) else "error"
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
            a["thumbs"] = [r[0] for r in con.execute(
                "SELECT id FROM files WHERE artist_id = ? AND path IS NOT NULL AND width IS NOT NULL "
                "ORDER BY COALESCE(posted, created) DESC, id DESC LIMIT 4", (a["id"],))]
            a["path"] = str(sync.artist_folder(a))
            a["folder"] = a["folder"] or ""
    return artists


def _display_name(name):
    return re.sub(r"\s+", " ", name or "").strip()[:200]


def name_from_url(url):
    """A name when no site says one: the account part of the link."""
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
    return jsonify(version=config.VERSION, library=sync.library(), sep=os.sep,
                   sites=[s.LABEL for s in sources.SITES], settings=db.settings(),
                   fields=[{"label": label, "example": example} for label, example in sources.FIELDS],
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
                    handle=p.get("handle", ""))
    except Exception as e:
        why = net.reason(e)
        info.update(status="login" if why.startswith(net.LOGIN) else "error", error=why)
    return jsonify(info)


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
    _background(sync.check_card, artist_id)
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
    sync.cancel(artist_id)
    with db.connect() as con:
        con.execute("DELETE FROM artists WHERE id = ?", (artist_id,))
    (config.AVATARS / ("%d.jpg" % artist_id)).unlink(missing_ok=True)
    return jsonify(ok=True)


@app.get("/api/avatar/<int:artist_id>")
def avatar(artist_id):
    path = config.AVATARS / ("%d.jpg" % artist_id)
    if not path.is_file():
        abort(404)
    resp = send_file(path, mimetype="image/jpeg")
    resp.cache_control.max_age = 86400          # the page asks with ?v=<when it changed>
    return resp


# ---- syncing -------------------------------------------------------------------

@app.post("/api/sync")
def start_sync():
    body = request.get_json(silent=True) or {}
    ids = [int(body["artist_id"])] if body.get("artist_id") else None
    return jsonify(added=sync.enqueue(ids))


@app.post("/api/sync/cancel")
def cancel_sync():
    body = request.get_json(silent=True) or {}
    return jsonify(ok=sync.cancel(int(body.get("artist_id") or 0)))


@app.get("/api/sync")
def sync_status():
    return jsonify(sync.status())


@app.get("/api/thumb/<int:file_id>")
def thumb(file_id):
    cached = config.THUMBS / ("%d.jpg" % file_id)
    if not cached.is_file():
        with db.connect() as con:
            row = con.execute("SELECT path FROM files WHERE id = ?", (file_id,)).fetchone()
        if not row or not row["path"] or not os.path.isfile(row["path"]):
            abort(404)
        try:
            imaging.thumbnail(row["path"], cached)
        except Exception:
            abort(404)
    resp = send_file(cached, mimetype="image/jpeg")
    resp.cache_control.max_age = 86400
    return resp


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
                "program": str(config.INSTALL), "userdata": str(config.USERDATA)}.get(target)
        if not path:
            abort(400)
    _open(path)
    return jsonify(ok=True)


@app.get("/api/info")
def info():
    try:
        lines = (config.LOG_DIR / "update.log").read_text(encoding="utf-8").splitlines()[-30:]
    except OSError:
        lines = []
    return jsonify(version=config.VERSION, python=platform.python_version(),
                   system="%s %s" % (platform.system(), platform.release()),
                   program=str(config.INSTALL), userdata=str(config.USERDATA),
                   library=sync.library(), repo="https://github.com/%s" % config.REPO,
                   update_log=lines, window=WINDOW is not None)


# ---- accounts -----------------------------------------------------------------------

def _forum_hosts():
    with db.connect() as con:
        urls = [r[0] for r in con.execute("SELECT url FROM sources")]
    return [accounts.host_of(u) for u in urls if sources.describe(u)["label"] == "XenForo"]


def _account_key(body):
    key = (body.get("key") or "").strip().lower()
    if body.get("forum"):                      # a forum typed in by hand: its host is the key
        key = "xenforo:" + accounts.host_of(sources.normalize(body["forum"]))
    try:
        accounts.describe(key)
    except KeyError:
        abort(400)
    return key


@app.get("/api/accounts")
def get_accounts():
    return jsonify(accounts=accounts.accounts(_forum_hosts()), window=WINDOW is not None)


@app.post("/api/accounts/login")
def account_login():
    key = _account_key(request.get_json(force=True) or {})
    if WINDOW is None:
        return jsonify(error="Logging in needs Sourcerer's own window. In the browser, "
                             "import a cookies.txt instead."), 501
    accounts.login_in_window(key)
    return jsonify(ok=True, key=key)


@app.post("/api/accounts/logout")
def account_logout():
    accounts.logout(_account_key(request.get_json(force=True) or {}))
    return jsonify(ok=True)


@app.post("/api/accounts/import")
def account_import():
    body = request.get_json(force=True) or {}
    key = _account_key(body)
    try:
        n = accounts.import_cookies_txt(key, body.get("text") or "")
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, key=key, cookies=n)


# ---- updates and repair --------------------------------------------------------------

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
    if action == "thumbs":
        shutil.rmtree(config.THUMBS, ignore_errors=True)
        return jsonify(message="Thumbnails are drawn again as the cards show them.")
    if action == "avatars":
        with db.connect() as con:
            ids = [r[0] for r in con.execute("SELECT id FROM artists")]
        _background(lambda: [sync.check_card(i) for i in ids])
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
