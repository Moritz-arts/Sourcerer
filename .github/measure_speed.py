"""What a speed level really reaches, with the real lanes and real seconds (no shrinking) -- run it for the level that is the DEFAULT before saying a change made
downloads faster (v0.69 measured Fast only, and Normal, which everybody runs, stayed at a file a second).

    python3 .github/measure_speed.py files  <level> [files=60] [size KB=330] [seconds the server takes to answer=0.15] [key=value[,value] ...]
    python3 .github/measure_speed.py forum  <level> [posts=8] [files per post=5] [page seconds=0.4] [file seconds=0.15] [key=value[,value] ...]

files: a made-up forum on loopback serves one file per request after the given time; the cookie login is faked, `net.download` runs in the level's own number of workers.
forum: a forum without the Media Gallery (an attachment browser): every file needs the page of its post (one thread per post, the data ids are not the attachment ids), then
       the file -- `xenforo.resolve` + `net.download`, the way a sync fetches them.
key=value (anywhere after the level) lays other numbers over the level's row of `net.PROFILES` (what a slider would do): `login_files=4 files=0.2 every=150,300`.
Needs what the program needs (flask, requests, pillow); the package is copied to a temporary folder, so no Userdata is made in the repository.
"""
import concurrent.futures
import hashlib
import http.server
import pathlib
import re
import shutil
import socketserver
import sys
import tempfile
import threading
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
WORK = pathlib.Path(tempfile.mkdtemp(prefix="sourcerer-speed-"))
shutil.copytree(REPO / "Sourcerer_files" / "sourcerer", WORK / "Sourcerer_files" / "sourcerer", ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(REPO / "Sourcerer_files" / "static", WORK / "Sourcerer_files" / "static")
shutil.copy(REPO / "Sourcerer_files" / "VERSION", WORK / "Sourcerer_files" / "VERSION")
sys.path.insert(0, str(WORK / "Sourcerer_files"))
from sourcerer import db, net  # noqa: E402
from sourcerer.sources import xenforo  # noqa: E402

db.init()
net._store = lambda key: None                                   # (the day's tally and rests are kept in the database: not for this)
net._flush = lambda: None
net.accounts.headers_for = lambda url, *a, **k: {"Cookie": "session=made-up"}
net._forum = lambda url: True                                    # a forum's login: it earns the quiet lane after twelve requests that went through
FILE = b"\xff\xd8\xff" + bytes(330 * 1024)
LOCK = threading.Lock()


class _Threaded(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def _serve(handler):
    srv = _Threaded(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % srv.server_address[1]


class _Quiet(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, code, body, ctype="text/html", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


def _tune(level, extras):
    for extra in extras:
        key, _, value = extra.partition("=")
        parts = [float(v) if "." in v else int(v) for v in value.split(",")]
        net.PROFILES[level][key] = tuple(parts) if len(parts) > 1 else parts[0]
    net.configure(speed=level)


def _run(jobs, one):
    """Every job in the level's own number of workers; (seconds, files, bytes)."""
    done = [0, 0]

    def wrapped(job):
        size = one(job)
        with LOCK:
            done[0] += 1
            done[1] += size
    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=net.profile()["parallel"]) as pool:
        list(pool.map(wrapped, jobs))
    return time.monotonic() - t0, done[0], done[1]


def files(level, count=60, size_kb=330, latency=0.15, extras=()):
    body = b"\xff\xd8\xff" + bytes(int(size_kb) * 1024)

    class Forum(_Quiet):
        def do_GET(self):
            time.sleep(float(latency))
            self.reply(200, body, "image/jpeg")
    base, folder = _serve(Forum), pathlib.Path(tempfile.mkdtemp(dir=WORK))
    _tune(level, extras)

    def one(n):
        part = net.download("%s/attachments/%d/" % (base, n), folder)[0]
        size = part.stat().st_size
        part.unlink()
        return size
    took, n, size = _run(range(int(count)), one)
    print("%-8s %3d files of %s KB, the server answers after %s s: %6.1f s  %5.2f files/s  %6.0f KB/s" % (level, n, size_kb, latency, took, n / took, size / 1024 / took))


def forum(level, posts=8, per=5, page_latency=0.4, file_latency=0.15, extras=()):
    posts, per, page_latency, file_latency = int(posts), int(per), float(page_latency), float(file_latency)
    md5, hits = hashlib.md5(FILE).hexdigest(), {"page": 0}

    def attachment(post, i):
        return 10000 + post * 10 + i

    def data(post, i):
        return attachment(post, i) + 100000                      # another number: as an attachment id the data id is somebody else's file

    class Forum(_Quiet):
        def do_GET(self):
            m = re.match(r"/posts/(\d+)/$", self.path)
            if m:
                return self.reply(303, b"", headers=[("Location", "/threads/t%s.%s/post-%s" % (m.group(1), m.group(1), m.group(1)))])
            m = re.match(r"/threads/t\d+\.(\d+)/post-\d+", self.path)
            if m:
                time.sleep(page_latency)
                with LOCK:
                    hits["page"] += 1
                p = int(m.group(1))
                page = '<span class="u-anchorTarget" id="post-%d"></span><article class="message" id="js-post-%d"><time datetime="2024-01-01T10:00:00+0000">x</time>' % (p, p)
                for i in range(per):
                    page += ('<li class="file"><a class="file-preview js-lbImage" href="/attachments/pic-jpg.%d/"><img src="/data/attachments/1/%d-%s.jpg" alt="pic%d_%d.jpg"></a></li>'
                             % (attachment(p, i), data(p, i), md5, p, i))
                return self.reply(200, ("<html><body>%s</article></body></html>" % page).encode())
            if self.path.startswith("/attachments/"):
                time.sleep(file_latency)
                return self.reply(200, FILE, "image/jpeg")
            self.reply(404, b"?")
    base, folder = _serve(Forum), pathlib.Path(tempfile.mkdtemp(dir=WORK))
    _tune(level, extras)
    items = []
    for p in range(1, posts + 1):                                # newest post first, as a listing hands them out
        for i in range(per):
            tile = (str(p), "/data/attachments/1/%d-%s.jpg" % (data(p, i), md5), str(data(p, i)), "pic%d_%d.jpg" % (p, i))
            items.append(xenforo._attachment_media(base, base + "/", xenforo._host(base), tile, {"url": "%s/posts/%d/" % (base, p), "date": "2024-01-01T10:00:00+0000"}))

    def one(media):
        url, check = xenforo.resolve(media)
        part = net.download(url, folder, media.mime)[0]
        if check:
            check(part)
        size = part.stat().st_size
        part.unlink()
        return size
    took, n, size = _run(items, one)
    print("%-8s %3d files in %d posts (page %.2f s, file %.2f s): %6.1f s  %5.2f files/s  %6.0f KB/s  (%d page reads)" % (
        level, n, posts, page_latency, file_latency, took, n / took, size / 1024 / took, hits["page"]))


if __name__ == "__main__":
    try:
        if len(sys.argv) < 3 or sys.argv[1] not in ("files", "forum") or sys.argv[2] not in net.PROFILES:
            sys.exit(__doc__)
        given = sys.argv[2:]
        {"files": files, "forum": forum}[sys.argv[1]](*[a for a in given if "=" not in a], extras=[a for a in given if "=" in a])
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
