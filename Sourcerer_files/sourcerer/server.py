"""The Flask app the window talks to: a JSON API under /api and the static page.

It listens on 127.0.0.1 only -- nothing here is meant to be reachable from
another machine.
"""
import logging
import os
import subprocess
import sys

from flask import Flask, jsonify, request, send_from_directory

from . import config, db, sources, sync

log = logging.getLogger(__name__)
app = Flask(__name__, static_folder=None)
WINDOW = None          # set by desktop.py when a pywebview window is open


def _artists():
    with db.connect() as con:
        artists = [dict(r) for r in con.execute(
            "SELECT a.*, (SELECT COUNT(*) FROM files f WHERE f.artist_id = a.id "
            "AND f.path IS NOT NULL) AS file_count FROM artists a ORDER BY a.name COLLATE NOCASE")]
        for a in artists:
            a["sources"] = [dict(r) for r in con.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM files f WHERE f.source_id = s.id "
                "AND f.path IS NOT NULL) AS file_count FROM sources s WHERE s.artist_id = ? "
                "ORDER BY s.id", (a["id"],))]
            for s in a["sources"]:
                # Recognised afresh on every read, so better detection reaches
                # sources saved before it (a pixiv link once stored as Mastodon).
                s["kind"] = sources.kind_of(s["url"])
                s["label"] = sources.label(s["kind"])
            a["folder"] = str(sync.artist_folder(a["name"]))
    return artists


def _clean(body):
    name = (body.get("name") or "").strip()
    if not name:
        return None, "The artist needs a name."
    urls = []
    for url in body.get("sources") or []:
        url = url.strip().rstrip("/")
        if url and "://" not in url:
            url = "https://" + url
        # Compared after completing them: "site/@a" and "https://site/@a" are one.
        if url and url not in urls:
            urls.append(url)
    return {"name": name[:200], "notes": (body.get("notes") or "").strip(), "urls": urls}, None


def _save_sources(con, artist_id, urls):
    """Keep the sources still listed (with their history), add new, drop the rest."""
    current = {r["url"]: r["id"] for r in con.execute(
        "SELECT id, url FROM sources WHERE artist_id = ?", (artist_id,))}
    for url, sid in current.items():
        if url not in urls:
            con.execute("DELETE FROM sources WHERE id = ?", (sid,))
    for url in urls:
        if url not in current:
            con.execute("INSERT INTO sources (artist_id, url, kind) VALUES (?, ?, ?)",
                        (artist_id, url, sources.kind_of(url)))


@app.get("/")
def index():
    return send_from_directory(config.STATIC, "index.html")


@app.get("/static/<path:name>")
def static_file(name):
    return send_from_directory(config.STATIC, name)


@app.get("/api/state")
def state():
    return jsonify(version=config.VERSION, library=sync.library(),
                   sites=[s.LABEL for s in sources.SITES],
                   artists=_artists(), sync=sync.status(), window=WINDOW is not None)


@app.post("/api/artists")
def create_artist():
    data, error = _clean(request.get_json(force=True))
    if error:
        return jsonify(error=error), 400
    with db.connect() as con:
        cur = con.execute("INSERT INTO artists (name, notes) VALUES (?, ?)",
                          (data["name"], data["notes"]))
        _save_sources(con, cur.lastrowid, data["urls"])
    return jsonify(id=cur.lastrowid)


@app.put("/api/artists/<int:artist_id>")
def update_artist(artist_id):
    data, error = _clean(request.get_json(force=True))
    if error:
        return jsonify(error=error), 400
    with db.connect() as con:
        row = con.execute("SELECT name FROM artists WHERE id = ?", (artist_id,)).fetchone()
        if not row:
            return jsonify(error="No such artist."), 404
        if row["name"] != data["name"]:
            _rename_folder(con, artist_id, row["name"], data["name"])
        con.execute("UPDATE artists SET name = ?, notes = ? WHERE id = ?",
                    (data["name"], data["notes"], artist_id))
        _save_sources(con, artist_id, data["urls"])
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
    with db.connect() as con:
        con.execute("DELETE FROM artists WHERE id = ?", (artist_id,))
    return jsonify(ok=True)


@app.post("/api/sync")
def start_sync():
    body = request.get_json(silent=True) or {}
    ids = [int(body["artist_id"])] if body.get("artist_id") else None
    if not sync.start(ids):
        return jsonify(error="A sync is already running."), 409
    return jsonify(ok=True)


@app.get("/api/sync")
def sync_status():
    return jsonify(sync.status())


@app.put("/api/settings")
def save_settings():
    folder = ((request.get_json(force=True) or {}).get("library") or "").strip()
    if not folder:
        return jsonify(error="Choose a folder."), 400
    folder = os.path.abspath(os.path.expanduser(folder))
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        return jsonify(error="Cannot use that folder: %s" % e), 400
    db.set_setting("library", folder)
    return jsonify(library=folder)


@app.post("/api/pick-folder")
def pick_folder():
    if WINDOW is None:
        return jsonify(error="Type the folder's path instead."), 501
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
