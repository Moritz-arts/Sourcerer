"""The Flask app the window talks to: a JSON API under /api and the static page.

It listens on 127.0.0.1 only -- nothing here is meant to be reachable from
another machine.
"""
import logging
import os
import subprocess
import sys

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from . import config, db, imaging, sources, sync

log = logging.getLogger(__name__)
app = Flask(__name__, static_folder=None)
WINDOW = None          # set by desktop.py when a pywebview window is open
THUMBS = config.USERDATA / "Thumbs"
LAYOUTS = ("together", "per_source")
DEDUPES = ("keep_all", "best", "master")


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
                a["sources"].append(s)
            a["thumbs"] = [r[0] for r in con.execute(
                "SELECT id FROM files WHERE artist_id = ? AND path IS NOT NULL AND width IS NOT NULL "
                "ORDER BY COALESCE(posted, created) DESC, id DESC LIMIT 4", (a["id"],))]
            a["folder"] = str(sync.artist_folder(a["name"]))
    return artists


def _clean(body):
    name = (body.get("name") or "").strip()
    if not name:
        return None, "Die Karte braucht einen Namen."
    urls = []
    for url in body.get("sources") or []:
        url = _normal(url)
        # Compared after completing them: "site/@a" and "https://site/@a" are one.
        if url and url not in urls:
            urls.append(url)
    return {"name": name[:200], "urls": urls, "master": _normal(body.get("master") or ""),
            "layout": body.get("layout") if body.get("layout") in LAYOUTS else "together",
            "dedupe": body.get("dedupe") if body.get("dedupe") in DEDUPES else "best"}, None


def _normal(url):
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "https://" + url
    return url


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
    con.execute("UPDATE artists SET name = ?, layout = ?, dedupe = ?, master_source_id = ? "
                "WHERE id = ?", (data["name"], data["layout"], data["dedupe"],
                                 master[0] if master else None, artist_id))


@app.get("/")
def index():
    return send_from_directory(config.STATIC, "index.html")


@app.get("/static/<path:name>")
def static_file(name):
    return send_from_directory(config.STATIC, name)


@app.get("/api/state")
def state():
    return jsonify(version=config.VERSION, library=sync.library(), sep=os.sep,
                   sites=[s.LABEL for s in sources.SITES],
                   artists=_artists(), sync=sync.status(), window=WINDOW is not None)


@app.post("/api/detect")
def detect():
    url = _normal((request.get_json(force=True) or {}).get("url"))
    return jsonify(url=url, **sources.describe(url))


@app.post("/api/artists")
def create_artist():
    body = request.get_json(force=True) or {}
    data, error = _clean(body)
    if error:
        return jsonify(error=error), 400
    with db.connect() as con:
        artist_id = con.execute("INSERT INTO artists (name) VALUES (?)", (data["name"],)).lastrowid
        _save(con, artist_id, data)
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
        row = con.execute("SELECT name FROM artists WHERE id = ?", (artist_id,)).fetchone()
        if not row:
            return jsonify(error="Diese Karte gibt es nicht mehr."), 404
        if row["name"] != data["name"]:
            _rename_folder(con, artist_id, row["name"], data["name"])
        _save(con, artist_id, data)
    if body.get("sync_now"):
        sync.enqueue([artist_id])
    return jsonify(ok=True)


def _rename_folder(con, artist_id, old, new):
    """The folder follows the name, so one artist never ends up in two folders."""
    src, dst = sync.artist_folder(old), sync.artist_folder(new)
    if src == dst or not src.is_dir() or dst.exists():
        return
    os.rename(src, dst)
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
    return jsonify(ok=True)


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
    cached = THUMBS / ("%d.jpg" % file_id)
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


@app.put("/api/settings")
def save_settings():
    folder = ((request.get_json(force=True) or {}).get("library") or "").strip()
    if not folder:
        return jsonify(error="Bitte einen Ordner wählen."), 400
    folder = os.path.abspath(os.path.expanduser(folder))
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        return jsonify(error="Dieser Ordner geht nicht: %s" % e), 400
    db.set_setting("library", folder)
    return jsonify(library=folder)


@app.post("/api/pick-folder")
def pick_folder():
    if WINDOW is None:
        return jsonify(error="Bitte den Pfad eintippen."), 501
    import webview
    # pywebview 6 turned FOLDER_DIALOG into a deprecated function; passing it
    # as the dialog type opens no folder dialog at all. FileDialog is the 6.x way.
    folder = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
    picked = WINDOW.create_file_dialog(folder, directory=sync.library())
    return jsonify(path=picked[0] if picked else None)


@app.post("/api/open-folder")
def open_folder():
    body = request.get_json(silent=True) or {}
    path = sync.library()
    if body.get("artist_id"):
        with db.connect() as con:
            row = con.execute("SELECT name FROM artists WHERE id = ?",
                              (int(body["artist_id"]),)).fetchone()
        if row:
            path = str(sync.artist_folder(row["name"]))
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
    return jsonify(ok=True)
