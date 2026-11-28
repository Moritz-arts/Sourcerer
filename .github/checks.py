"""The program's own checks: what the code promises, against made-up sites, on a copy of the program (so no Userdata is written into the repository).

    python .github/checks.py          (needs: pip install flask requests pillow gallery-dl)

Run by .github/workflows/checks.yml on every pull request, and by hand before pushing a change to what is checked here:

* a XenForo forum without the Media Gallery, whose attachment numbers differ from their data ids: the viewer and a sync get the attachment the
  post's page names, a guess is checked against the file's md5, nothing wrong is shown, cached or saved (sources/xenforo.py: resolve);
* a media gallery's tiles: the small picture of each, not an avatar, not another picture's (gdl_run.py: tile_thumb);
* the speed choice: the table, the pace of a login's files and pages, the lanes' concurrency, what an old settings table becomes, the settings API (net.py,
  db.py, server.py);
* the sliders under the levels and the daily limits (net.py: clean_tune, _row, day_limit, server.py: /api/speed);
* what a refused file does to a site (net.py: _refusal): one file is one refusal and it takes eight different ones in a row, a refused page or list still
  takes three;
* what a card already has (sync.py: _saved_keys): asked for by name, a file whose folder was deleted is fetched again, one missing from a folder that is
  still there stays deleted, a sweep and an offline library fetch nothing again; a saved file gets its post's date, and where the site gave none the
  listing's order among the posts around it (a cut-off run carries on below what it saved, a file fetched again gets its old time), the images of one post
  apart; restamp and "Put files in upload order" (sync._stamp, _timeline, _ordered, restamp);
* files with a login go several at once, a new one started every `files` seconds (net.py: _Polite bulk lane, login_files), one at a time on a site that said a word;
* a sync that was stopped (the connection dropped, Cancel, a crash) is carried on: what was saved stays, the source is walked again, a dropped connection is not counted against
  a file, a cut-off file is no file, leftover .part files are cleaned; the automatic sync queues the cards with auto-download and is due after Sourcerer was closed
  for days (sync.py: _sync_artist, _fetch, _auto_due, enqueue);
* Refresh all also looks at the accounts every login follows (server.py: start_sync -> follows.look_async), one card's Refresh and a download do not;
* a sweep leaves a source read less than 12 hours ago alone, on every site, a card asked for by name never (sync.py: _cooling), the scan at start is on by default,
  and an artist opened on its own is shown from a snapshot of the last twelve hours (gallery.py: FRESH_ARTIST);
* gallery.picture for a site with no resolver (the booru-like case the forum fix must not change).
* a forum's videos, animated WebPs and crops (xenforo._media, net.fetch_picture / sniff, gallery.picture, server.py): the type comes from the extension and
  from the file's first bytes when the server says only octet-stream, a clip is held to a larger limit than a picture and kept apart in memory, a video with
  no poster has no tile picture, a clip is served in ranges (206), the whole picture of a cropped tile is the original.

A failing check starts with FAIL and makes the exit code 1.
"""
import copy
import hashlib
import http.server
import io
import pathlib
import re
import shutil
import socketserver
import sys
import tempfile
import threading
import time
import types

REPO = pathlib.Path(__file__).resolve().parents[1]
WORK = pathlib.Path(tempfile.mkdtemp(prefix="sourcerer-checks-"))
shutil.copytree(REPO / "Sourcerer_files" / "sourcerer", WORK / "Sourcerer_files" / "sourcerer", ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(REPO / "Sourcerer_files" / "static", WORK / "Sourcerer_files" / "static")
shutil.copy(REPO / "Sourcerer_files" / "VERSION", WORK / "Sourcerer_files" / "VERSION")
sys.path.insert(0, str(WORK / "Sourcerer_files"))

from PIL import Image                                                        # noqa: E402

from sourcerer import db, gallery, gdl_run, net, server                      # noqa: E402
from sourcerer.sources import Media, kinds, mastodon, poipiku, xenforo                                 # noqa: E402

FAILS = []


def check(ok, text, extra=None):
    print(("ok    " if ok else "FAIL  ") + text + ("" if ok else "   <- %r" % (extra,)), flush=True)
    if not ok:
        FAILS.append(text)


def jpeg(color, size):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG", quality=90)
    return out.getvalue()


def serve(handler):
    class Threaded(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
    srv = Threaded(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % srv.server_address[1]


db.init()
net._store = lambda key: None            # (the day's tally and rests are kept in the database: not for these checks)
net._flush = lambda: None


# ---- a forum without the Media Gallery: attachment ids are not data ids ----------------------------------------------------------------------

ORIG = {9001: (101, "a.jpg", jpeg((220, 30, 30), (640, 480))), 9002: (102, "b.jpg", jpeg((30, 200, 30), (640, 480))),
        9003: (103, "c.jpg", jpeg((30, 30, 220), (640, 480)))}                    # attachment id -> (data id, file name, the file)
STRANGERS = {101: jpeg((230, 230, 20), (640, 480)), 102: jpeg((20, 230, 230), (640, 480)), 103: jpeg((230, 20, 230), (640, 480))}   # what a data id is as an attachment id
MD5 = {a: hashlib.md5(v[2]).hexdigest() for a, v in ORIG.items()}
THUMBS = {v[0]: jpeg(c, (64, 48)) for v, c in zip(ORIG.values(), [(220, 30, 30), (30, 200, 30), (30, 30, 220)])}
POST_OF = {9001: 501, 9002: 501, 9003: 502}
MODE = {"anchors": True, "same_ids": False, "inline501": False, "hits": []}


def small(att):
    data, _name, _orig = ORIG[att]
    return "/data/attachments/%d/%d-%s.jpg" % (data // 1000, data, MD5[att])


def thread_page():
    def post(pid, atts, inline=()):
        out = '<span class="u-anchorTarget" id="post-%d"></span><article class="message" id="js-post-%d"><time datetime="2024-0%d-01T10:00:00+0000">x</time>' % (pid, pid, pid - 500)
        for a in atts if MODE["anchors"] else ():
            out += ('<li class="file"><a class="file-preview js-lbImage" href="/attachments/%s.%d/" target="_blank">\n<img src="%s" alt="%s"></a></li>'
                    % (ORIG[a][1].replace(".", "-"), a, small(a), ORIG[a][1]))
        for a in inline:
            out += ('<div class="bbImageWrapper js-lbImage" data-src="/attachments/%s.%d/"><img src="/attachments/%s.%d/" alt="%s" class="bbImage"></div>'
                    % (ORIG[a][1].replace(".", "-"), a, ORIG[a][1].replace(".", "-"), a, ORIG[a][1]))
        return out + "</article>"
    first = post(501, [], inline=[9001, 9002]) if MODE["inline501"] else post(501, [9001, 9002])      # (inline: no tile names the data, only the picture's name does)
    return "<html><body>" + first + post(502, [], inline=[9003]) + "</body></html>"


class Forum(http.server.BaseHTTPRequestHandler):
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

    def do_GET(self):
        path = self.path
        MODE["hits"].append(path)
        if path.startswith("/index.php?media/"):
            return self.reply(404, b"no gallery here")
        if re.match(r"/members/tester\.12/attachment-browser/(page-\d+/)?$", path):
            tiles = "".join('<a href="/posts/%d/"><img src="%s" alt="%s"></a>\n' % (POST_OF[a], small(a), ORIG[a][1]) for a in (9003, 9002, 9001))
            return self.reply(200, ("<html><body>%s</body></html>" % tiles if "page-" not in path else "<html></html>").encode())
        m = re.match(r"/posts/(\d+)/$", path)
        if m:
            return self.reply(303, b"", headers=[("Location", "/threads/art.7/post-%s" % m.group(1))])
        if path.startswith("/threads/art.7/"):
            return self.reply(200, thread_page().encode())
        m = re.match(r"/attachments/(?:[^/]*\.)?(\d+)/?$", path)
        if m:
            a = int(m.group(1))
            if MODE["same_ids"]:                                  # a forum whose numbers agree: the data id IS the attachment id
                for data, _n, orig in ORIG.values():
                    if data == a:
                        return self.reply(200, orig, "image/jpeg")
            if a in ORIG:
                return self.reply(200, ORIG[a][2], "image/jpeg")
            if a in STRANGERS:
                return self.reply(200, STRANGERS[a], "image/jpeg")
            return self.reply(404, b"gone")
        m = re.match(r"/data/attachments/\d+/(\d+)-[0-9a-f]+\.jpg$", path)
        if m and int(m.group(1)) in THUMBS:
            return self.reply(200, THUMBS[int(m.group(1))], "image/jpeg")
        self.reply(404, b"?")


def forum_checks():
    base = serve(Forum)

    def forget():
        xenforo._attachments.clear()
        xenforo._unsettled.clear()
        xenforo._read_posts.clear()
        gallery._cache.clear()
        MODE["hits"].clear()

    forget()
    xenforo._gallery_route.clear()
    items = [m for page in xenforo.pages(base + "/members/tester.12/") for m in page]
    check(len(items) == 3, "an attachment browser's three tiles are three items", len(items))
    by_data = {m.remote_key.rpartition(":a")[2]: m for m in items}
    check(set(by_data) == {"101", "102", "103"}, "keyed by the data id, as they always were (remote_key is forever)", sorted(by_data))
    a = by_data["101"]
    check(a.url.endswith("/attachments/101/"), "the listed address is the data id as an attachment id (the wrong one)", a.url)

    url, test = xenforo.resolve(a)                                 # the post's page names the attachment
    check(url.endswith("/attachments/a-jpg.9001/") and test is None, "resolve gives the attachment's own address", (url, test))
    check(net.fetch_picture(url)[1] == ORIG[9001][2], "and it serves the right file")
    check(net.fetch_picture(a.url)[1] != ORIG[9001][2], "the old address served another member's file (the bug)")
    check(xenforo.resolve(by_data["102"])[0].endswith("/attachments/b-jpg.9002/") and len([h for h in MODE["hits"] if h.startswith("/threads/")]) == 1,
          "the post's other attachment comes from the same page")

    forget()                                                       # a sync resolves many files at once: one read of a post's page answers them all
    answers = []
    start = threading.Barrier(len(items))

    def ask(m):
        start.wait()
        answers.append(xenforo.resolve(m)[0])
    workers = [threading.Thread(target=ask, args=(m,)) for m in items]
    [w.start() for w in workers]
    [w.join() for w in workers]
    pages = [h for h in MODE["hits"] if h.startswith(("/threads/", "/posts/"))]
    check(len(answers) == 3 and 1 <= len([h for h in pages if h.startswith("/threads/")]) <= 2,
          "files asked for at once cost a read of a page for all of them (three files, two posts), not one each", pages)
    forget()
    MODE["inline501"] = True                                       # two pictures shown inline in one post: the one read names both (by their names), the second is no guess
    got = [xenforo.resolve(by_data[k])[0] for k in ("101", "102")]
    MODE["inline501"] = False
    check(got[0].endswith("/attachments/a-jpg.9001/") and got[1].endswith("/attachments/b-jpg.9002/")
          and len([h for h in MODE["hits"] if h.startswith("/threads/")]) == 1, "two inline pictures of a post are both named by one read of its page", got)
    forget()
    MODE["anchors"] = False                                        # a page that does not name them: the post is read once, not once per attachment
    for m in (by_data["101"], by_data["102"]):
        try:
            xenforo.resolve(m)
        except Exception:
            pass
    check(len([h for h in MODE["hits"] if h.startswith("/threads/")]) == 1, "a post whose page names nothing is not read again for its next attachment",
          [h for h in MODE["hits"] if h.startswith("/threads/")])
    MODE["anchors"] = True
    forget()

    order = {m.remote_key.rpartition(":a")[2]: i for i, m in enumerate(items)}       # the gallery's large view, mid and grid picture
    gallery._galleries["forum"] = types.SimpleNamespace(items=[(types.SimpleNamespace(site=xenforo), m) for m in items], seen=0)
    check(gallery.picture("forum", order["101"], "large")[1] == ORIG[9001][2], "gallery.picture(large) is the right file")
    check(gallery.picture("forum", order["101"], "mid")[1] == ORIG[9001][2], "gallery.picture(mid) is the right file")
    check(gallery.picture("forum", order["101"], "thumb")[1] == THUMBS[101], "gallery.picture(thumb) is the forum's small copy")

    MODE["anchors"] = False                                        # a page that names nothing: the data id is tried, and refused when it is another file
    forget()
    got = xenforo.resolve(by_data["101"])
    check(got[1] is not None and got[0].endswith("/attachments/101/"), "no anchor and an md5 in the small copy: the data id, with a check", got)
    try:
        gallery.picture("forum", order["101"], "large")
        shown = "shown"
    except Exception as e:
        shown = str(e)
    check("another file" in shown, "the check refuses another member's file in the viewer", shown)
    check(not any(k[0] == "forum" and str(k[2]).endswith("/attachments/101/") for k in gallery._cache), "and nothing wrong is kept for a download to find")
    MODE["hits"].clear()
    for _ in range(3):
        try:
            gallery.picture("forum", order["101"], "large")
        except Exception:
            pass
    fetched = [h for h in MODE["hits"] if h.startswith(("/attachments/", "/threads/"))]
    check(len([h for h in fetched if h.startswith("/attachments/")]) == 0 and len([h for h in fetched if h.startswith("/threads/")]) == 0,
          "a viewer opened again does not fetch the wrong original or the page again", fetched)
    forget()
    got = xenforo.resolve(by_data["103"])                          # a picture shown inline at full size: found by its name in its own post
    check(got[0].endswith("/attachments/c-jpg.9003/") and got[1] is None, "an inline picture is found by its name in its own post", got)

    forget()                                                       # a page that names an attachment on another host: never gone to
    real = thread_page
    globals()["thread_page"] = lambda: real().replace('href="/attachments/a-jpg.9001/"', 'href="http://169.254.169.254/attachments/a-jpg.9001/"')
    try:
        got = xenforo.resolve(a)
    finally:
        globals()["thread_page"] = real
    check(got[0].startswith(base) and got[1] is not None, "an address on another host is not followed (the data id is tried, with its check)", got)

    MODE["same_ids"] = True                                        # a forum whose numbers agree still works: the md5 passes
    forget()
    check(gallery.picture("forum", order["101"], "large")[1] == ORIG[9001][2], "equal numbers and no anchors: the data id's file passes its md5")
    MODE["same_ids"] = False
    MODE["anchors"] = True

    forget()                                                       # a download, sync's way
    folder = pathlib.Path(tempfile.mkdtemp(dir=WORK))
    url, test = xenforo.resolve(a)
    part, _sha, _ext, _name = net.download(url, folder)
    check(part.read_bytes() == ORIG[9001][2], "a download saves the right file")
    MODE["anchors"] = False
    forget()
    url, test = xenforo.resolve(a)
    part, _sha, _ext, _name = net.download(url, folder)
    try:
        test(part)
        verdict = "accepted"
    except RuntimeError:
        verdict = "refused"
    check(verdict == "refused", "a download of another member's file is refused by its check")
    MODE["anchors"] = True


# ---- a media gallery's tiles ------------------------------------------------------------------------------------------------------------------

def tile_checks():
    page = '''<div class="itemList">
<div class="itemList-item js-inlineModContainer" data-author="x">
  <a href="/media/first-one.123/"><span class="xfmgThumbnail"><img class="xfmgThumbnail-image" src="/data/xfmg/thumbnail/0/123-aaaa.jpg" alt="first"></span></a>
  <div><span class="avatar"><img src="/data/avatars/s/0/12.jpg"></span><time class="u-dt" datetime="2024-05-01T12:00:00+0000">May 1</time></div>
</div>
<div class="itemList-item js-inlineModContainer" data-author="y">
  <div><span class="avatar avatar--s"><img src="/data/avatars/s/0/13.jpg" class="avatar-u13-s"></span></div>
  <a href="/media/second.124/"><img class="lazyload" data-src="/data/xfmg/thumbnail/0/124-bbbb.jpg" src="data:image/gif;base64,R0lGOD"></a>
  <time datetime="2024-05-02T12:00:00+0000">May 2</time>
</div>
<div class="itemList-item js-inlineModContainer" data-author="z"><a href="/media/third.125/">no picture here</a></div>
</div><footer><time datetime="2030-01-01T00:00:00+0000"></time><img src="/styles/logo.png"></footer>'''
    dates, thumbs = {}, {}
    gdl_run.tile_dates(page, dates, thumbs)
    check(thumbs.get("first-one.123") == "/data/xfmg/thumbnail/0/123-aaaa.jpg", "a tile's picture, not the avatar after it", thumbs)
    check(thumbs.get("second.124") == "/data/xfmg/thumbnail/0/124-bbbb.jpg", "a lazy-loading tile: data-src, the avatar before it skipped", thumbs)
    check(len(thumbs) == 2 and "third.125" not in dates, "a tile with no picture gives none; the footer's logo is nobody's", (thumbs, dates))
    check(dates.get("first-one.123", "").startswith("2024-05-01") and dates.get("second.124", "").startswith("2024-05-02"), "the dates are still read", dates)
    plain = {}
    gdl_run.tile_dates(page, plain)
    check(len(plain) == 2, "without thumbs it is as it was")
    f = {"id": "123", "thumb": "/data/xfmg/thumbnail/0/123-aaaa.jpg"}
    check(xenforo._tile_thumb("https://forum.example", f) == "https://forum.example/data/xfmg/thumbnail/0/123-aaaa.jpg", "an address on the forum")
    check(xenforo._tile_thumb("https://forum.example", {"id": "124", "thumb": "/data/avatars/s/0/13.jpg"}) == "", "an avatar is not the picture's own")
    check(xenforo._tile_thumb("https://forum.example", {"id": "12", "thumb": "/data/xfmg/thumbnail/0/123-aaaa.jpg"}) == "", "another id's picture is not this one's (12 is not 123)")
    check(xenforo._tile_thumb("https://forum.example", {"id": "123", "thumb": None}) == "", "null: none")
    check(xenforo._tile_thumb("https://forum.example", {"id": "123", "thumb": "http://127.0.0.1/x/123-a.jpg"}) == "", "a page never sends Sourcerer into the machine")


# ---- the speed choice -------------------------------------------------------------------------------------------------------------------------

def speed_checks():
    need = {"parallel", "per_host", "pause", "gap", "pace", "files", "login_files", "every", "rest", "look", "preview", "browse"}
    check(set(net.PROFILES) == {"careful", "normal", "fast"} and all(set(p) == need for p in net.PROFILES.values()), "three levels, each says everything")
    n = net.PROFILES["normal"]
    check((n["parallel"], n["per_host"], n["pause"], n["gap"]) == (24, 32, 0.1, (3, 15)), "normal is what the settings were (24 at once, 32 per site, 0.1 s, a gap of 3-15 s)")
    net.configure(speed="nonsense")
    check(net.profile() is net.PROFILES["normal"], "an unknown word changes nothing")

    site_url = "https://forum.example/attachments/1/"
    site = net.site_of(site_url)
    net._state["unfriendly"], net._state["paused"], net._state["spent"] = {}, {}, {}
    net.configure(speed="careful")
    check(net._rhythm(site_url, True)[0] == 2.0, "careful files: LOGIN_PACE")
    net.configure(speed="normal")
    got = net._rhythm(site_url, True)
    check(got[0] == 0.2 and got[1] == (150, 300) and got[2] == (6, 20), "normal files: a new one every 0.2 s, a rest of 6-20 s every 150-300", got)
    check(net._rhythm(site_url, False)[0] == 2.0, "a page keeps LOGIN_PACE whatever is chosen")
    net.configure(speed="fast")
    got = net._rhythm(site_url, True)
    check(got[0] == 0.1 and got[1] is None, "fast files: a new one every 0.1 s, no rest", got)
    net._state["unfriendly"][site] = time.time() + 3600
    got = net._rhythm(site_url, True)
    check(got[0] == 2.0 and got[1] == (20, 40), "a site that said a word is read carefully even under fast", got)
    net._state["unfriendly"].clear()
    net._fast.add(site)
    net.configure(speed="careful")
    check(net._rhythm(site_url, True)[0] == 1.0, "careful keeps what a quiet forum has earned")
    net._fast.clear()

    saved, jitter, pace = copy.deepcopy(net.PROFILES), net.JITTER, net.LOGIN_PACE           # the lanes in time: seconds shrunk tenfold, the ratios are the point
    for p in net.PROFILES.values():
        for k in ("pause", "pace", "files", "look"):
            p[k] /= 10
        p["preview"], p["browse"] = (p["preview"][0], p["preview"][1] / 10), (p["browse"][0], p["browse"][1] / 10)
    net.JITTER, net.LOGIN_PACE = (1.0, 1.0), 0.2

    def lane(url, n, hold, **kw):
        login, starts, live, peak, lock = kw.pop("login", True), [], [0], [0], threading.Lock()
        t0 = time.monotonic()

        def one():
            with net._Polite(url, login, **kw):
                with lock:
                    starts.append(time.monotonic() - t0)
                    live[0] += 1
                    peak[0] = max(peak[0], live[0])
                time.sleep(hold)
                with lock:
                    live[0] -= 1
        threads = [threading.Thread(target=one) for _ in range(n)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        return sorted(starts), peak[0]

    def fresh(name):
        net._hosts.clear()
        net.configure(speed=name)

    try:
        fresh("normal")
        starts, peak = lane(site_url, 12, 0.3, browse=True)
        check(peak == 6, "normal: pictures from a login site six at once, a browser's way", (peak, starts[-1]))
        fresh("careful")
        starts, peak = lane(site_url, 9, 0.3, browse=True)
        check(peak == 3, "careful: three at once", peak)
        fresh("normal")
        check(lane("https://cdn.example/a.jpg", 12, 0.3, login=False, preview=True)[1] == 6, "normal: pictures from a host with no login six at once")
        fresh("careful")
        check(lane("https://cdn.example/a.jpg", 12, 0.3, login=False, preview=True)[1] == 4, "careful: four at once (what it was)")
        net.HOSTS["downloads.fanbox.cc"] = (2, 0.05)
        fresh("fast")
        check(lane("https://downloads.fanbox.cc/images/a.jpg", 6, 0.4, browse=True)[1] == 2, "fast: Fanbox's file host keeps its own two at once")
        for name, at_once, apart in (("careful", 1, 0.2), ("normal", 4, 0.02), ("fast", 6, 0.01)):
            fresh(name)
            starts, peak = lane(site_url, 8, 0.15, bulk=True)
            gaps = [b - a for a, b in zip(starts, starts[1:])]
            check(peak == at_once and all(g >= apart - 0.01 for g in gaps),
                  "%s: files with a login %d at once, a new one at least %.2f s after the last START" % (name, at_once, apart), (peak, gaps))
        net.HOSTS["slow.example"] = (2, 0.06)                           # a host that keeps a pace three times the level's (0.02 s shrunk): its rests come after a third of the files
        fresh("normal")
        lane("https://slow.example/a.jpg", 1, 0.01, bulk=True)
        lane(site_url, 1, 0.01, bulk=True)
        own, quick = [e["break"] for k, e in net._hosts.items() if k[0] == "slow.example" and k[-1]], [e["break"] for k, e in net._hosts.items() if k[0] == "forum.example" and k[-1]]
        check(own and 50 <= own[0] <= 100 and quick and 150 <= quick[0] <= 300, "normal: a host with a slower pace of its own rests after fewer files, a free one after 150-300", (own, quick))
        fresh("normal")                                                  # v0.69 made files "several at once" and measured it on fast only: normal stayed at a file a second
        starts, peak = lane(site_url, 24, 0.02, bulk=True)
        mean = (starts[-1] - starts[0]) / (len(starts) - 1)
        check(mean <= 0.033, "normal: files with a login are not held to less than three a second (seconds shrunk tenfold)", (mean, peak))
        fresh("careful")
        starts, peak = lane(site_url, 4, 0.05, bulk=True)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        check(peak == 1 and all(g >= 0.2 + 0.04 for g in gaps), "careful: one file at a time, the gap counted from the END of the last one", (peak, gaps))
        fresh("fast")
        lane(site_url, 1, 0.01, login=True)                              # (pages and lists keep the one-at-a-time lane of their own)
        starts, peak = lane(site_url, 4, 0.1)
        check(peak == 1, "fast: pages and lists with a login are still one at a time", peak)
        net._state["unfriendly"][site] = time.time() + 3600
        fresh("fast")
        starts, peak = lane(site_url, 4, 0.05, bulk=True)
        check(peak == 1, "a site that said a word is read one file at a time, whatever is chosen", peak)
        net._state["unfriendly"].clear()
        net.HOSTS["slow.example"] = (2, 0.05)
        fresh("fast")
        starts, peak = lane("https://slow.example/a.jpg", 6, 0.15, bulk=True)
        check(peak == 2, "a touchy host keeps its own two at once", peak)
        net.HOSTS["www.pixiv.net"] = (1, 1.5)
        for name in ("careful", "normal", "fast"):
            fresh(name)
            look = net.PROFILES[name]["look"]
            starts, _peak = lane("https://www.pixiv.net/ajax/x", 3, 0.02, first=True)
            gaps = [b - a for a, b in zip(starts, starts[1:])]
            check(all(look - 0.02 <= g <= look + 0.5 for g in gaps), "%s: a page somebody waits for goes every ~%.2f s (the profile's, not pixiv's own 1.5 s)" % (name, look), gaps)
    finally:
        net.PROFILES.clear()
        net.PROFILES.update(saved)
        net.JITTER, net.LOGIN_PACE = jitter, pace
        net._hosts.clear()
    net.configure(speed="normal")


# ---- a refused file is about that file, a refused page about the login ------------------------------------------------------------------------

def refusal_checks():
    """2026-11-03: three attachments of one post, behind a permission, answered 403 in a row and "it refused the login three times in a row"
    rested a forum for hours while the login worked."""
    class Refusing(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            number = self.path.rstrip("/").rpartition("/")[2]
            if self.path.startswith("/attachments/") and number.isdigit() and int(number) >= 100:
                body, code, kind = jpeg((10, 120, 10), (32, 24)), 200, "image/jpeg"
            else:                                                  # the forum's own error page, as a member without the permission sees it
                body, code, kind = b"<html><head><title>Oops! We ran into some problems. | Forum</title></head><body>No permission</body></html>", 403, "text/html"
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    base = serve(Refusing)
    site, folder = net.site_of(base), pathlib.Path(tempfile.mkdtemp(dir=WORK))
    saved = (copy.deepcopy(net.PROFILES), net.JITTER, net.LOGIN_PACE, net.accounts.headers_for)
    net.accounts.headers_for = lambda url, *args, **kwargs: {"Cookie": "session=made-up"}          # the made-up forum is a login's site
    net.JITTER, net.LOGIN_PACE = (1.0, 1.0), 0.0
    for p in net.PROFILES.values():
        p["files"], p["look"], p["pause"], p["pace"] = 0.0, 0.0, 0.0, 0.0

    def fresh():
        net._refused.clear()
        net._hosts.clear()
        net._state["paused"], net._state["unfriendly"] = {}, {}

    def asked(path, page=False):
        try:
            net.get_json(base + path) if page else net.download(base + path, folder)
        except Exception:
            return "refused"
        return "served"

    try:
        fresh()
        for _ in range(5):
            asked("/attachments/7/")
        check(net.paused(base) is None, "one refused file, asked again and again, is one refusal", net.paused(base))
        for n in range(1, 8):
            asked("/attachments/%d/" % n)
        check(net.paused(base) is None, "seven different refused files do not rest the site", net.paused(base))
        check(not net._stored("unfriendly").get(site), "a refused file is no word about how Sourcerer behaves", net._stored("unfriendly"))
        asked("/attachments/8/")
        got = net.paused(base)
        check(got is not None and "8 files in a row" in got[1], "the eighth different one does, and says what it was", got)
        net.lift(base)
        check(net.paused(base) is None, "a login saved anew ends it")

        fresh()
        for n in range(1, 4):
            asked("/attachments/%d/" % n)
        check(asked("/attachments/200/") == "served", "a file that comes through is served as before")
        for n in range(4, 11):
            asked("/attachments/%d/" % n)
        check(net.paused(base) is None, "a file that came through starts the count afresh", net.paused(base))

        fresh()
        for n in range(3):
            asked("/list/%d" % n, page=True)
        got = net.paused(base)
        check(got is not None and "the login three times" in got[1], "three refused pages still rest the site: that is the login's verdict", got)
    finally:
        net.PROFILES.clear()
        net.PROFILES.update(saved[0])
        net.JITTER, net.LOGIN_PACE, net.accounts.headers_for = saved[1], saved[2], saved[3]
        fresh()


# ---- the sliders under the levels, and the daily limits ----------------------------------------------------------------------------------------

def tune_checks():
    client = server.app.test_client()
    client.put("/api/speed", json={"reset": "limits"})
    client.put("/api/settings", json={"speed": "normal"})
    net._state["unfriendly"], net._state["paused"], net._state["spent"] = {}, {}, {}
    state = client.get("/api/state").get_json()["speed"]
    names = {k["key"] for k in state["knobs"]}
    want = {"parallel", "per_host", "login_files", "pause", "pace", "files", "every", "rest", "gap_min", "gap_max", "look", "preview_n", "browse_n",
            "limit_pixiv", "limit_patreon", "limit_x", "limit_fanbox", "limit_fantia", "limit_poipiku", "limit_other"}
    check(names == want, "every important value has a slider, and every daily limit", sorted(names ^ want))
    check(state["level"] == "normal" and not state["tuned"] and state["values"]["parallel"] == 24 and state["values"]["limit_x"] == 600,
          "the sliders start at the level's own values and the default limits", state["values"])
    check(all(k["low"] <= state["levels"][lv][k["key"]] <= k["high"] for lv in state["levels"] for k in state["knobs"]), "every level lies inside every slider's range")
    check(all(abs(k["step"] * round(state["levels"][lv][k["key"]] / k["step"]) - state["levels"][lv][k["key"]]) < 1e-9 for lv in state["levels"] for k in state["knobs"]),
          "... and on its step, so a level's value shows exactly")

    got = client.put("/api/speed", json={"tune": {"parallel": 10, "files": 3, "every": 0, "gap_min": 5, "gap_max": 9, "preview_n": 3, "limit_x": 100}}).get_json()["speed"]
    row = net.profile()
    check(got["tuned"] and got["limits_changed"] and got["level"] == "normal" and row["parallel"] == 10 and row["files"] == 3.0 and row["every"] is None
          and tuple(row["gap"]) == (5.0, 9.0) and tuple(row["preview"]) == (3, 0.0), "moved sliders are laid over the level's row", row)
    check(row["per_host"] == 32 and row["look"] == 0.5 and row["pace"] == 2.0 and tuple(row["browse"]) == (6, 0.0), "and everything else stays the level's")
    check(net.day_limit("x") == 100 and net.day_limit("pixiv") == 1500 and net.day_limit("forum.example") == 3000, "a daily limit is the user's, the others stay the defaults")
    url = "https://forum.example/attachments/1/"
    check(net._rhythm(url, True)[0] == 3.0 and net._rhythm(url, True)[1] is None, "the files slider paces the files, and no breaks", net._rhythm(url, True))
    check(net._rhythm(url, False)[0] == 2.0, "pages keep their own pace")

    client.put("/api/speed", json={"tune": {"pace": 0.5, "files": 0.1}})
    check(net._rhythm(url, False)[0] == 0.5 and net._rhythm(url, True)[0] == 0.1, "fast sliders are honoured while the site says nothing")
    net._state["unfriendly"][net.site_of(url)] = time.time() + 3600
    got = (net._rhythm(url, False), net._rhythm(url, True))
    check(all(g[0] == net.LOGIN_PACE and g[1] == net.READ_EVERY for g in got), "a site that said a word is read carefully whatever the sliders say", got)
    net._state["unfriendly"].clear()
    client.put("/api/speed", json={"tune": {"every": 30}})
    got = net._rhythm(url, True)
    check(got[1] == (30, 60) and got[2], "breaks asked for on a level that had none last what the usual ones do", got)

    client.put("/api/speed", json={"reset": "sliders"})
    check(set(net.tuning()) == {"limit_x"} and net.profile() is net.PROFILES["normal"], "reset takes the sliders back to the level and keeps the limits", net.tuning())
    got = client.put("/api/speed", json={"tune": {"parallel": 999, "pace": 0.01, "per_host": 24, "pause": 0.1, "files": "soon"}}).get_json()["speed"]["values"]
    check(got["parallel"] == 64 and got["pace"] == 0.5 and got["per_host"] == 24 and "pause" not in net.tuning() and "files" not in net.tuning(),
          "a value is clamped into its range; one that equals the level's, or is no number, is no change", (got, net.tuning()))
    check(client.put("/api/speed", json={"tune": {"nonsense": 1}}).status_code == 400 and client.put("/api/speed", json={"tune": [1]}).status_code == 400,
          "an unknown slider and a wrong shape are refused")
    client.put("/api/speed", json={"tune": {"parallel": None}})
    check("parallel" not in net.tuning(), "null takes one slider back")

    client.put("/api/speed", json={"tune": {"parallel": 12}})
    client.put("/api/settings", json={"speed": "fast"})
    check(net.profile() is net.PROFILES["fast"] and net.tuning() == {"limit_x": 100}, "choosing a level takes the sliders back and keeps the limits", net.tuning())
    net._limits["tune"], net._limits["row"] = {}, None
    net.apply_settings()
    check(net.tuning() == {"limit_x": 100} and net.profile() is net.PROFILES["fast"], "what was moved is read back from the database at the next start", net.tuning())
    client.put("/api/settings", json={"speed": "normal"})

    net._state["spent"], net._state["paused"] = {}, {}
    for _ in range(99):
        net.spend("https://x.com/home")
    check(net.paused("https://x.com/") is None, "99 requests of a limit of 100 rest nothing")
    net.spend("https://x.com/home")
    got = net.paused("https://x.com/")
    check(got is not None and "today's 100 requests" in got[1], "the 100th ends the day, with the user's figure", got)
    check(not net.scan_room("https://x.com/home"), "and a sweep leaves the site alone from half of it on")
    client.put("/api/speed", json={"reset": "limits"})
    check(net.day_limit("x") == 600 and not net.tuning(), "the limits can be reset too")
    net._state["spent"], net._state["paused"] = {}, {}


def settings_checks():
    def scenario(old):
        with db.connect() as con:
            con.execute("DELETE FROM settings WHERE key IN ('speed', 'speed_v1', 'parallel', 'per_host', 'pace_ms', 'login_gap', 'login_pace')")
            for k, v in old.items():
                con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))
        db.init()
        with db.connect() as con:
            left = {r[0] for r in con.execute("SELECT key FROM settings WHERE key IN ('parallel', 'per_host', 'pace_ms', 'login_gap', 'login_pace')")}
        return db.get_setting("speed"), left
    for old, want in (({}, "normal"), ({"login_gap": "careful"}, "careful"), ({"login_gap": "fast"}, "fast"), ({"login_pace": "fast"}, "fast"),
                      ({"login_gap": "normal"}, "normal"), ({"per_host": "2"}, "careful"), ({"parallel": "4", "pace_ms": "500"}, "careful"),
                      ({"parallel": "24", "per_host": "32", "pace_ms": "100"}, "normal"), ({"login_gap": "bogus"}, "normal")):
        got, left = scenario(old)
        check(got == want and not left, "old settings %s become %r, and the five keys go" % (old or "(none)", want), (got, left))
    db.set_setting("speed", "fast")
    db.init()
    check(db.get_setting("speed") == "fast", "a second start keeps the choice")
    client = server.app.test_client()
    got = client.get("/api/settings").get_json()
    check(got["settings"]["speed"] == "fast" and set(got["speed"]["levels"]) == {"careful", "normal", "fast"} and "parallel" not in got["settings"],
          "the settings API says the one choice and the table", sorted(got["settings"]))
    check(client.put("/api/settings", json={"speed": "careful"}).status_code == 200 and net.profile() is net.PROFILES["careful"], "choosing careful reaches net at once")
    check(client.put("/api/settings", json={"speed": "warp"}).status_code == 400, "an unknown level is refused")
    check(client.put("/api/settings", json={"parallel": "8"}).status_code == 400, "the old keys are gone")
    state = client.get("/api/state").get_json()
    check(bool(state.get("speed", {}).get("knobs")) and state["settings"]["speed"] == "careful", "/api/state carries them for the page")
    client.put("/api/settings", json={"speed": "normal"})


# ---- gallery.picture for a site that needs no resolver ----------------------------------------------------------------------------------------

def gallery_checks():
    files = {"/small.jpg": jpeg((200, 10, 10), (80, 60)), "/big.jpg": jpeg((10, 200, 10), (1600, 1200))}

    class Cdn(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = files.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    base = serve(Cdn)

    def item(**kw):
        fields = dict(remote_key="k", url=base + "/big.jpg", post_url="p", posted="", name="n", thumb=base + "/small.jpg", large=base + "/big.jpg", preview_headers={})
        fields.update(kw)
        return Media(**fields)
    items = [item(), item(thumb=""), item(thumb=base + "/gone.jpg"), item(thumb="", large="")]
    gallery._galleries["cdn"] = types.SimpleNamespace(items=[(types.SimpleNamespace(site=types.SimpleNamespace()), m) for m in items], seen=0)
    check(gallery.picture("cdn", 0, "thumb")[1] == files["/small.jpg"], "a site's small copy is the grid picture")
    check(gallery.picture("cdn", 0, "large")[1] == files["/big.jpg"], "large is the large")
    made = gallery.picture("cdn", 1, "thumb")
    check(made[0] == "image/jpeg" and made[1] != files["/big.jpg"] and len(made[1]) < 20000, "no small copy: one is made from the original", len(made[1]))
    check(gallery.picture("cdn", 2, "thumb")[1] == files["/big.jpg"], "a small copy that is not there: the original will do")
    check(gallery.picture("cdn", 3, "large")[1] == files["/big.jpg"], "no large address: the url")


def media_checks():
    def webp(frames):
        out = io.BytesIO()
        pics = [Image.new("RGB", (64, 48), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))][:frames]
        pics[0].save(out, "WEBP", save_all=frames > 1, append_images=pics[1:], duration=80, loop=0)
        return out.getvalue()
    clip = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + bytes(range(256)) * 40
    files = {"/clip.mp4": (clip, "application/octet-stream"), "/loop.webp": (webp(3), "application/octet-stream"), "/still.webp": (webp(1), "image/webp"),
             "/wide.jpg": (jpeg((10, 120, 200), (1200, 400)), "image/jpeg"), "/crop.jpg": (jpeg((10, 120, 200), (200, 200)), "image/jpeg"),
             "/noise": (bytes(range(256)) * 20, "application/octet-stream"), "/page": (b"<html>no</html>", "text/html"),
             "/huge.mp4": (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * (41 << 20), "video/mp4"),
             "/big.zip": (b"PK\x03\x04" + b"\x00" * (60 << 20), "application/octet-stream"),
             "/big.mp4": (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * (60 << 20), "video/mp4"),
             "/song.mp3": (b"ID3\x04\x00\x00" + bytes(range(256)) * 20, "application/octet-stream"),
             "/photo.heic": (b"\x00\x00\x00\x18ftypheic" + bytes(range(256)) * 20, "application/octet-stream")}
    sent = {}

    class Cdn(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            got = files.get(self.path)
            if got is None:
                self.send_response(404)
                self.end_headers()
                return
            sent[self.path] = 0                      # (before anything is sent: the reader may leave on the headers)
            self.send_response(200)
            self.send_header("Content-Type", got[1])
            self.send_header("Content-Length", str(len(got[0])))
            self.end_headers()
            try:
                for at in range(0, len(got[0]), 1 << 16):         # (in chunks: what a reader that gave up never received is counted)
                    self.wfile.write(got[0][at:at + (1 << 16)])
                    sent[self.path] += 1 << 16
                    time.sleep(0.001)                # (so a reader that has left is noticed within a few chunks, not after the kernel's buffers are full)
            except ConnectionError:                  # (a reader that gave up on a file above its limit)
                pass
    base = serve(Cdn)

    check([xenforo._type_of(x) for x in ("mp4", "Movie.WEBM", ".gif", "x.webp", "a.b.mov", "", None, "xyz")] ==
          ["video/mp4", "video/webm", "image/gif", "image/webp", "video/quicktime", "", "", ""], "a forum file's type comes from its extension")
    check([kinds.type_of(x) for x in ("a.mp3", "b.ZIP", "c.psd", "d.heic", "e.tif", "f.m2ts")] ==
          ["audio/mpeg", kinds.FILE, kinds.FILE, "image/heic", "image/tiff", "video/mp2t"], "sounds, plain files and more formats are told by their extension")
    check(kinds.typed("x.mp4") == {"mime": "video/mp4", "video": True} and kinds.typed("x.mp3")["video"] and not kinds.typed("x.png")["video"] and
          kinds.typed(None) == {"mime": "", "video": False}, "Fanbox and Fantia files get their type from the name (a sound plays in the clip's player)")
    check(mastodon._media("m.example", {"url": "https://m.example/@a/1", "created_at": ""}, {"id": "1", "type": "audio", "url": "https://m.example/f/1"},
                          "https://m.example/f/1").mime == "audio/mpeg", "a Mastodon sound is typed as one")
    m = xenforo._media("https://forum.example", "forum.example", {"id": "5", "url": "https://forum.example/media/x.5/full", "ext": "mp4",
                                                                   "thumb": "/data/xfmg/thumbnail/0/5-ab.jpg"})
    check(m.video and m.mime == "video/mp4" and m.crop and m.preview_headers == {}, "a media gallery's clip is a video, its poster a crop", m)
    m = xenforo._media("https://forum.example", "forum.example", {"id": "6", "url": "https://forum.example/media/y.6/full", "ext": "webp"})
    check(not m.video and m.mime == "image/webp" and not m.crop, "a WebP is no video; no thumbnail, no crop", m)
    check(net.sniff(files["/clip.mp4"][0]) == "video/mp4" and net.sniff(files["/loop.webp"][0]) == "image/webp" and net.sniff(b"nothing") == "" and
          net.sniff(b"\x1a\x45\xdf\xa3" + b"\0" * 12) == "video/webm" and net.sniff(b"\x00\x00\x00\x18ftypavif" + b"\0" * 4) == "image/avif" and
          net.sniff(files["/photo.heic"][0]) == "image/heic" and net.sniff(files["/song.mp3"][0]) == "audio/mpeg" and
          net.sniff(b"\x00\x00\x00\x18ftypM4A " + b"\0" * 4) == "audio/mp4", "the first bytes tell a picture, a clip and a sound apart (a HEIC is no clip)")
    got = net.fetch_picture(base + "/loop.webp")
    check(got[0] == "image/webp" and got[1] == files["/loop.webp"][0], "a WebP sent as octet-stream is accepted and named by its bytes", got[0])
    got = net.fetch_picture(base + "/clip.mp4")
    check(got[0] == "video/mp4", "a clip sent as octet-stream is a video", got[0])
    for path, why in (("/noise", "octet-stream that is nothing known"), ("/page", "an HTML page")):
        try:
            net.fetch_picture(base + path)
            check(False, "refused: " + why)
        except RuntimeError as e:
            check("sent no picture" in str(e), "refused: " + why, str(e))
    got = net.fetch_picture(base + "/huge.mp4")
    check(got[0] == "video/mp4" and len(got[1]) > 40 << 20, "a video above a picture's limit is still fetched", got[0])
    try:
        net.fetch_picture(base + "/huge.mp4", video_limit=1 << 20)
        check(False, "a video is held to its own limit")
    except ValueError:
        check(True, "a video is held to its own limit")
    try:
        net.fetch_picture(base + "/big.zip")
        check(False, "a zip sent as octet-stream is refused")
    except net.NoPicture:
        check(sent.get("/big.zip", 0) < 30 << 20, "... from its first bytes: the 60 MB behind them are not downloaded", sent.get("/big.zip"))
    try:
        net.fetch_picture(base + "/big.mp4", allow_video=False)
        check(False, "a clip is refused where a still is wanted")
    except net.NoPicture:
        check(sent.get("/big.mp4", 0) < 30 << 20, "a clip is refused where a still is wanted, before its body is read", sent.get("/big.mp4"))
    try:
        net.fetch_picture(base + "/clip.mp4", allow_video=False)
        check(False, "an octet-stream clip is refused where a still is wanted")
    except net.NoPicture:
        check(True, "an octet-stream clip is refused where a still is wanted")
    try:
        net.fetch_picture(base + "/loop.webp", limit=100)
        check(False, "a generic picture is held to the caller's limit")
    except ValueError:
        check(True, "a generic picture is held to the caller's limit (an avatar's, an icon's), not to a clip's")
    got = net.fetch_picture(base + "/song.mp3")
    check(got[0] == "audio/mpeg", "a sound is accepted for the viewer", got[0])
    check(imaging_animated(files["/loop.webp"][0]) and not imaging_animated(files["/still.webp"][0]) and not imaging_animated(b"junk"),
          "an animated WebP is told from a still one")

    def item(**kw):
        fields = dict(remote_key="k", url=base + "/wide.jpg", post_url="p", posted="", name="n", thumb="", large=base + "/wide.jpg", preview_headers={})
        fields.update(kw)
        return Media(**fields)
    site = types.SimpleNamespace()
    items = [item(url=base + "/clip.mp4", large=base + "/clip.mp4", video=True, mime="video/mp4"),                       # 0: a video with no poster
             item(url=base + "/loop.webp", large=base + "/loop.webp", mime="image/webp"),                                # 1: animated, no small copy
             item(url=base + "/still.webp", large=base + "/still.webp", mime="image/webp"),                              # 2: still, no small copy
             item(thumb=base + "/crop.jpg", crop=True),                                                                  # 3: a crop of a wide picture
             item(url=base + "/clip.mp4", large=base + "/clip.mp4", thumb=base + "/crop.jpg", video=True, crop=True),    # 4: a video with a poster
             item(url=base + "/clip.mp4", large=base + "/clip.mp4"),                                                     # 5: a clip nobody called one
             item(url=base + "/big.zip", large=base + "/big.zip", mime=kinds.FILE),                                      # 6: a plain attachment
             item(url=base + "/song.mp3", large=base + "/song.mp3", mime="audio/mpeg"),                                  # 7: a sound
             item(url=base + "/wide.jpg", thumb=base + "/crop.jpg", crop=True, remote_key="saved")]                      # 8: a crop that is in the library
    before = (gallery._cached_video[0], gallery._cached[0])          # (other groups leave their galleries' pictures in memory)
    gallery._galleries["vid"] = types.SimpleNamespace(items=[(types.SimpleNamespace(site=site), m) for m in items], seen=0)
    try:
        gallery.picture("vid", 0, "thumb")
        check(False, "a video with no poster has no picture")
    except gallery.NoPicture:
        check(True, "a video with no poster has no picture")
    check(gallery.picture("vid", 0, "large")[0] == "video/mp4", "... and plays from its own address")
    got = gallery.picture("vid", 1, "thumb")
    check(got[0] == "image/webp" and got[1] == files["/loop.webp"][0], "an animated WebP is shown as the file when it has no small copy", got[0])
    got = gallery.picture("vid", 2, "thumb")
    check(got[0] == "image/jpeg", "a still WebP gets a small picture made from it", got[0])
    check(gallery.picture("vid", 3, "thumb")[1] == files["/crop.jpg"][0], "a crop's grid picture is the forum's small copy")
    asked = []
    real = net.fetch_picture
    net.fetch_picture = lambda *a, **kw: (asked.append(kw), real(*a, **kw))[1]
    try:
        whole = gallery.picture("vid", 3, "whole")
        check(asked and not asked[0].get("first") and asked[0].get("allow_video") is False, "the whole picture of a tile is no priority request and no clip", asked)
        asked.clear()
        gallery.picture("vid", 3, "large")
        check(asked and asked[0].get("first") and asked[0].get("allow_video"), "the viewer's own fetch is", asked)
    finally:
        net.fetch_picture = real
    shape = Image.open(io.BytesIO(whole[1])).size
    check(whole[0] == "image/jpeg" and shape == (gallery.WHOLE, gallery.WHOLE // 3) and len(whole[1]) < len(files["/wide.jpg"][0]),
          "the whole picture laid over a crop is a screen-sized copy in the picture's own shape, not the original", shape)
    check(gallery.picture("vid", 3, "whole") is gallery.picture("vid", 3, "whole"), "... kept apart from the original (asked once)")
    check(gallery.picture("vid", 4, "thumb")[1] == files["/crop.jpg"][0], "a video's poster is its small copy")
    gallery.picture("vid", 5, "large")
    check(gallery._cached_video[0] >= len(clip) and gallery._cached[0] >= len(files["/wide.jpg"][0]), "videos and pictures are counted apart",
          (gallery._cached_video[0], gallery._cached[0]))
    gallery._forget("vid")
    check((gallery._cached_video[0], gallery._cached[0]) == before, "closing a gallery gives its clips and pictures back", ((gallery._cached_video[0], gallery._cached[0]), before))
    gallery._galleries["vid"] = types.SimpleNamespace(items=[(types.SimpleNamespace(site=site), m) for m in items], seen=0)
    for n, why in ((5, "an untyped clip asked for as a grid picture"), (6, "a zip asked for as a grid picture"), (7, "a sound asked for as a grid picture")):
        sent.clear()
        try:
            gallery.picture("vid", n, "thumb")
            check(False, why + " is refused")
        except net.NoPicture:
            check(max(sent.values() or [0]) < 30 << 20, why + " is refused without downloading it", dict(sent))
    gallery.picture("vid", 5, "large")
    try:
        gallery.picture("vid", 5, "thumb")
        check(False, "a clip the viewer cached is not handed to the grid as a picture")
    except net.NoPicture:
        check(True, "a clip the viewer cached is not handed to the grid as a picture")
    gallery._forget("vid")
    gallery._galleries.pop("vid", None)

    # the items a page gets
    g = gallery._Gallery.__new__(gallery._Gallery)
    g.id, g.sharp, g.saved, g.told = "vid", False, {}, {}
    row = {"id": 1}
    src = types.SimpleNamespace(label="XenForo", kind="xenforo", host="forum.example", row=row, site=site, artist={"id": 7, "name": "Artist A"})
    g.items = {n + 1: (src, m) for n, m in enumerate(items)}
    g.saved = {(7, "saved"): {"id": 99, "path": "/x/y.jpg", "width": 1200, "sha256": "ab" * 32}}
    g._there = lambda r: True
    got = {n: g.item(n) for n in g.items}
    check(got[1]["video"] and got[1]["thumb"] == "", "a clip with no poster: no tile picture is asked for", got[1])
    check(got[4]["crop"] and got[4]["whole"].endswith("/4/whole") and "crop" not in got[1], "a cropped tile says where its whole picture is")
    check("crop" not in got[5] and "crop" not in got[6] and "crop" not in got[3], "a clip (typed or not) and a picture with no small copy have no crop to unfold")
    check(got[8]["video"] and got[8]["thumb"] == "", "a sound is played, and has no tile picture", got[8])
    check(got[7]["thumb"] == "" and not got[7]["video"] and "crop" not in got[7], "a plain attachment has no tile picture, no crop and no player", got[7])
    check(got[9]["saved"] and "crop" not in got[9] and "whole" not in got[9] and got[9]["thumb"].startswith("/api/thumb/99"),
          "a downloaded picture shows the library's thumbnail, in its own shape: no crop, no whole picture to ask the forum for", got[9])

    # served in ranges, and "whole" is a size
    client = server.app.test_client()
    gallery._galleries["vid2"] = types.SimpleNamespace(items=[(types.SimpleNamespace(site=site), items[5])], seen=0)
    r = client.get("/api/gallery/vid2/0/large", headers={"Range": "bytes=4-11"})
    check(r.status_code == 206 and r.data == clip[4:12] and r.headers.get("Content-Range") == "bytes 4-11/%d" % len(clip), "a clip is served in ranges", (r.status_code, r.headers))
    r = client.get("/api/gallery/vid2/0/large")
    check(r.status_code == 200 and r.headers.get("Accept-Ranges") == "bytes" and r.data == clip and r.headers["Content-Type"].startswith("video/mp4"),
          "... and whole with the range promised", (r.status_code, r.headers))
    gallery._galleries["vid3"] = types.SimpleNamespace(items=[(types.SimpleNamespace(site=site), items[0])], seen=0)
    check(client.get("/api/gallery/vid3/0/thumb").status_code == 404, "a video with no poster answers 404, not 502")
    check(client.get("/api/gallery/vid2/0/whole").status_code == 404 and client.get("/api/gallery/vid2/0/bogus").status_code == 404,
          "a clip is no whole picture (404); other sizes are not sizes")
    for name in ("vid2", "vid3"):
        gallery._forget(name)
        gallery._galleries.pop(name, None)


def imaging_animated(data):
    from sourcerer import imaging
    return imaging.animated(data)


# ---- PoiPiku: a visitor's 640 px copy, a member's original ------------------------------------------------------------------------------------

def poipiku_checks():
    from sourcerer import accounts, sources
    for url in ("https://poipiku.com/2/", "https://poipiku.com/2/13202427.html", "http://www.poipiku.com/2", "https://poipiku.com/IllustListPcV.jsp?PG=1&ID=2&KWD="):
        check(sources.kind_of(url) == "poipiku" and poipiku.normalize(url) == "https://poipiku.com/2/", "a PoiPiku link is the artist's page: " + url)
    for url in ("https://poipiku.com/", "https://poipiku.com/MyHomePcV.jsp?ID=-1", "https://poipiku.com/IllustListPcV.jsp?PG=0&ID=-1", "https://poipiku.com.evil.example/2/"):
        check(sources.kind_of(url) != "poipiku", "...but not " + url)
    check(sources.account_key("https://poipiku.com/2/") == "poipiku" and accounts.key_for("https://cdn.poipiku.com/x") == "poipiku", "the login's cookies go to the picture host too")
    check(accounts.SITES["poipiku"][3]({"POIPIKU_LK": ""}) is False and accounts.SITES["poipiku"][3]({"POIPIKU_LK": "abc"}) is True,
          "a visitor's empty POIPIKU_LK is no login")
    guest = poipiku._media({"url": "https://cdn.poipiku.com/000000002/013202411_YJMjMxhKf.png_640.jpg", "post": "13202427", "num": 1, "user": "2"})
    check(guest.remote_key == "poipiku:13202427:1" and guest.filename == "013202411_YJMjMxhKf_640.jpg" and guest.mime == "image/jpeg"
          and guest.thumb == "https://cdn.poipiku.com/000000002/013202411_YJMjMxhKf.png_360.jpg" and guest.post_url == "https://poipiku.com/2/13202427.html",
          "a visitor's copy is named for what it is and gets the site's small rendition", guest)
    member = poipiku._media({"url": "https://cdn.poipiku.com/000000002/013202411_YJMjMxhKf.png", "post": "13202427", "num": 1, "user": "2"})
    check(member.remote_key == guest.remote_key and member.filename == "013202411_YJMjMxhKf.png" and member.mime == "image/png"
          and member.thumb == guest.thumb and member.large == member.url, "a member's original has the same key, its own name and the same small rendition", member)
    signed = "https://cdn.poipiku.com/000000002/013202411_YJMjMxhKf.png?Expires=1893456000&Signature=aB-c~d_e&Key-Pair-Id=K2ABC"
    mine = poipiku._media({"url": signed, "post": "13202427", "num": 1, "user": "2"})
    check(mine is not None and mine.url == signed and mine.large == signed and mine.remote_key == guest.remote_key and mine.filename == "013202411_YJMjMxhKf.png"
          and mine.mime == "image/png" and mine.thumb == guest.thumb, "a member's signed original (a query on the address) is kept, named without the signature, its small rendition is unsigned", mine)
    for icon in ("https://cdn.poipiku.com/img/publish_pass.png", "https://cdn.poipiku.com/assets/img/x.png", "https://evil.example/000000002/a.png", ""):
        check(poipiku._media({"url": icon, "post": "1", "num": 1, "user": "2"}) is None, "an icon or a foreign address is no file of the artist: " + icon)

    # the accounts a login follows: the authors of the Following feed (the cards of the public pages), paged by PG
    def card(uid, name, avatar="profile_20200101000000.jpeg"):
        return ('<div class="IllustThumb"><a class="IllustUser" href="/%s/"><img class="IllustUserThumb" src="https://cdn.poipiku.com/%09d/%s_120.jpg" alt="%s" decoding="async"/>'
                '<h2 class="IllustUserName">%s</h2></a><a class="IllustThumbImg" href="/%s/9.html"></a></div>' % (uid, int(uid), avatar, name, name, uid))

    def feed(page, cards, nxt):
        bar = "".join('<span class="PageBarItemFrame"><a class="BtnBase PageBarItem" href="/MyHomePcV.jsp?PG=%d">x</a></span>' % n for n in nxt)
        return "<html><body><section>%s</section><nav class=\"PageBar\">%s</nav></body></html>" % ("".join(cards), bar)

    pages_of = {0: feed(0, [card("2", "Artist A"), card("2", "Artist A"), card("3", "Artist &amp; B", "default_user.jpg")], [0, 1]),
                1: feed(1, [card("3", "Artist &amp; B", "default_user.jpg"), card("4", "Artist C")], [0, 1, 2]),
                2: feed(2, [card("4", "Artist C")], [1, 2])}
    asked, real = [], net.get_text
    net.get_text = lambda url, params=None, headers=None: (asked.append(dict(params or {})), (pages_of.get((params or {}).get("PG"), ""), url))[1]
    try:
        (name, pages), = list(poipiku.following("poipiku"))
        got = [a for page in pages for a in page]
        check([a["url"] for a in got] == ["https://poipiku.com/2/", "https://poipiku.com/3/", "https://poipiku.com/4/"] and name == ""
              and [a["name"] for a in got] == ["Artist A", "Artist & B", "Artist C"] and [p["PG"] for p in asked] == [0, 1, 2],
              "the Following feed is read page by page to the end, an author once, names unescaped", (got, asked))
        check(got[0]["avatar"] == "https://cdn.poipiku.com/000000002/profile_20200101000000.jpeg_120.jpg" and got[1]["avatar"] == "",
              "an author's own picture is the avatar, the default picture is none", got)
        pages_of.clear()
        pages_of[0] = "<html><body><a class=\"BtnBase LoginButton\" href=\"/LoginFormEmailPcV.jsp\">Login</a></body></html>"
        try:
            list(list(poipiku.following("poipiku"))[0][1])
            raised = False
        except RuntimeError as e:
            raised = "log in again" in str(e)
        check(raised, "a feed that shows the login page is an expired login, said plainly")
        pages_of[0] = feed(0, [], [])
        check(not [a for _n, pages in poipiku.following("poipiku") for page in pages for a in page], "a login that follows nobody gives an empty list, no error")
        pages_of[0] = feed(0, [card("5", "Artist D")], [0])
        asked.clear()
        check([a["url"] for _n, pages in poipiku.following("poipiku") for page in pages for a in page] == ["https://poipiku.com/5/"] and len(asked) == 1,
              "no link to a next page: the walk ends there, it never goes on by a guess", asked)
    finally:
        net.get_text = real


def resume_checks():
    import os
    from sourcerer import sources, sync
    root = pathlib.Path(tempfile.mkdtemp(prefix="sourcerer-resume-"))
    folder = root / "Artist R"
    folder.mkdir()
    N, GOOD = 30, 12
    state = {"drop": True}

    def picture(n):
        return jpeg(((n * 37) % 256, (n * 91) % 256, (n * 53) % 256), (64, 48))

    class Cdn(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def finish(self):
            try:
                super().finish()
            except ConnectionError:                  # (the connection this handler closed on purpose)
                pass

        def do_GET(self):
            n = int(self.path.strip("/").split(".")[0])
            if (state["drop"] and n >= GOOD) or n == 999:           # the connection is gone / closes in the middle of a file
                body = picture(1)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body) * 2 if n == 999 else len(body)))
                self.end_headers()
                if n == 999:
                    self.wfile.write(body)
                self.close_connection = True
                self.connection.close()
                return
            body = picture(n)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    base = serve(Cdn)

    def pages(url):
        for first in range(0, N, 10):                                     # three pages of ten, newest first
            yield [Media(remote_key="r%d" % n, url="%s/%d.jpg" % (base, n), post_url="p", posted="", name="n%d" % n, filename="") for n in range(first, first + 10)]
    fake = types.SimpleNamespace(KIND="fake", LABEL="Fakesite", match=lambda url: url.startswith("https://fake.test/"), pages=pages, profile=lambda url: {})
    sources.SITES.insert(0, fake)
    retries, net.RETRIES = net.RETRIES, 1
    old_library = db.get_setting("library")
    try:
        with db.connect() as con:
            con.execute("DELETE FROM artists WHERE id = 21")
            con.execute("INSERT INTO artists (id, name, folder, layout, dedupe, auto_download, listed) VALUES (21, 'Artist R', ?, 'together', 'keep_all', 1, 0)", (str(folder),))
            con.execute("INSERT INTO sources (id, artist_id, kind, url, complete) VALUES (21, 21, 'fake', 'https://fake.test/r', 1)")    # (read to its end by an earlier sync)
        old = folder / ".aaaaaaaaaaaa.part"
        old.write_bytes(b"x")
        os.utime(old, (time.time() - 7200, time.time() - 7200))
        fresh = folder / ".bbbbbbbbbbbb.part"
        fresh.write_bytes(b"x")
        sync._sync_artist(21)                                              # the connection drops after the first files
        with db.connect() as con:
            saved = con.execute("SELECT COUNT(*) FROM files WHERE artist_id = 21 AND path IS NOT NULL").fetchone()[0]
            complete = con.execute("SELECT complete FROM sources WHERE id = 21").fetchone()[0]
            counted = con.execute("SELECT COUNT(*) FROM failures WHERE artist_id = 21").fetchone()[0]
        check(0 < saved < N, "an interrupted sync keeps what it saved and not more", saved)
        check(complete == 0, "... and leaves the source to be walked again (its early stop would skip what was never saved)", complete)
        check(counted == 0, "a connection that dropped is not counted against the files (they are not given up on)", counted)
        check(not old.exists() and fresh.exists(), "the leftover of a cut-off download is cleaned up, one that is being written is not")
        check(not [f for f in folder.glob(".*.part") if f != fresh], "no unfinished file stays behind")
        state["drop"] = False
        sync._sync_artist(21)                                              # later: the connection is back
        with db.connect() as con:
            files = [r[0] for r in con.execute("SELECT path FROM files WHERE artist_id = 21 AND path IS NOT NULL")]
            complete = con.execute("SELECT complete FROM sources WHERE id = 21").fetchone()[0]
        check(len(files) == N and all(os.path.isfile(f) for f in files), "the next sync downloads the files that are missing, all %d are there" % N, len(files))
        check(complete == 1, "... and the source is complete again")
        # a file that was cut off in the middle is no file
        try:
            net.download("%s/999.jpg" % base, folder)
            check(False, "a connection that closes in the middle of a file is an error")
        except Exception:
            check(not [f for f in folder.glob(".*.part") if f != fresh], "a connection that closes in the middle of a file is an error, no part of it is kept")
    finally:
        net.RETRIES = retries
        sources.SITES.remove(fake)

    # automatic sync: what it queues, and when
    sync._running.pop(21, None)                                            # (the worker takes a card out of this when it is done; the test ran it by hand)
    queued_before = list(sync._queue)
    spawn, sync._spawn = sync._spawn, lambda: None
    try:
        with db.connect() as con:
            con.execute("DELETE FROM artists WHERE id IN (31, 32, 33, 34)")
            for i, (name, auto, listed, last) in enumerate((("Auto", 1, 0, "datetime('now')"), ("Manual", 0, 0, "datetime('now')"),
                                                            ("Listed auto", 1, 1, "datetime('now')"), ("Never read", 0, 1, "NULL"))):
                con.execute("INSERT INTO artists (id, name, auto_download, listed, last_sync) VALUES (?, ?, ?, ?, %s)" % last, (31 + i, name, auto, listed))
        sync._queue.clear()
        sync.enqueue(auto=True)
        queued, modes = set(sync._queue), dict(sync._modes)
        check(21 in queued and 31 in queued, "automatic sync queues the cards with auto-download", sorted(queued))
        check(32 not in queued and 33 not in queued, "... and not the ones without it, nor a card that is only listed")
        check(34 in queued and modes.get(34) == "scan" and modes.get(31) is None, "... a listed card never read is only scanned, the others download", modes)
        sync._queue.clear()
        client = server.app.test_client()
        client.post("/api/artists/33/auto-download", json={"on": True})
        with db.connect() as con:
            listed = con.execute("SELECT listed FROM artists WHERE id = 33").fetchone()[0]
        sync.enqueue(auto=True)
        check(listed == 0 and 33 in sync._queue, "switching auto-download on takes a listed card into the routine", (listed, sorted(sync._queue)))
    finally:
        sync._spawn = spawn
        sync._queue.clear()
        sync._queue.extend(queued_before)
        sync._modes.clear()
        sync._auto.clear()
    now = time.time()
    saved_settings = {k: db.get_setting(k) for k in ("auto_sync", "auto_hours", "next_auto", "last_auto")}
    try:
        db.set_setting("auto_sync", "1")
        db.set_setting("auto_hours", "6")
        db.set_setting("next_auto", str(now + 3600))
        check(not sync._auto_due(now), "automatic sync waits for its time")
        db.set_setting("next_auto", str(now - 5 * 86400))                  # (Sourcerer was closed for days)
        check(sync._auto_due(now), "... and is due as soon as Sourcerer runs after it was closed for days")
        nxt = float(db.get_setting("next_auto"))
        check(now + 6 * 3600 * 0.85 - 1 <= nxt <= now + 6 * 3600 * 1.2 + 1 and not sync._auto_due(now), "... then the next one is set hours ahead", nxt - now)
        db.set_setting("auto_sync", "0")
        db.set_setting("next_auto", str(now - 100))
        check(not sync._auto_due(now), "switched off, it never starts")
    finally:
        for k, v in saved_settings.items():
            db.set_setting(k, v or "")


# ---- what a card already has, and the date of a saved file ------------------------------------------------------------------------------------

def library_checks():
    import os
    from sourcerer import sync
    root = pathlib.Path(tempfile.mkdtemp(prefix="sourcerer-library-"))
    folder = root / "Artist A"
    folder.mkdir()
    (folder / "kept.jpg").write_bytes(b"x")                         # saved and still there
    (root / "Artist B").mkdir()                                     # a second artist whose folder is still there ...
    with db.connect() as con:
        con.execute("DELETE FROM artists")
        con.execute("INSERT INTO artists (id, name) VALUES (1, 'Artist A')")
        for key, path in (("a", folder / "kept.jpg"), ("b", folder / "culled.jpg"),             # b: gone from a folder that is still there
                          ("c", root / "Gone Folder" / "c.jpg"), ("d", root / "Gone Folder" / "d.jpg"),   # the folder was deleted
                          ("e", None)):                                                          # a duplicate that was never kept
            con.execute("INSERT INTO files (artist_id, remote_key, path) VALUES (1, ?, ?)", (key, str(path) if path else None))
    artist = {"id": 1, "name": "Artist A", "folder": str(folder)}
    with db.connect() as con:
        asked = sync._saved_keys(con, artist, restore=True)
        swept = sync._saved_keys(con, artist, restore=False)
        offline = sync._saved_keys(con, dict(artist, folder=str(root / "unplugged" / "Artist A")), restore=True)
    check(asked == {"a", "b", "e"}, "asked for by name: a deleted folder's files are fetched again, a culled file and a duplicate stay known", sorted(asked))
    check(swept == {"a", "b", "c", "d", "e"}, "a sweep never fetches what its folder lost", sorted(swept))
    check(offline == {"a", "b", "c", "d", "e"}, "a library that is not there is no deleted artist", sorted(offline))
    # the row of a fetched-again file points at the new place; a copy that is not kept leaves no path, so it stays known
    with db.connect() as con:
        sync._record(con, {"id": 1}, {"id": None}, types.SimpleNamespace(remote_key="c", post_url="", posted=""), "sha", str(folder / "c.jpg"), None, 1, 1, 1)
        sync._record(con, {"id": 1}, {"id": None}, types.SimpleNamespace(remote_key="d", post_url="", posted=""), "sha", None, None, 1, 1, 1)
        rows = {r[0]: r[1] for r in con.execute("SELECT remote_key, path FROM files")}
    check(rows["c"] == str(folder / "c.jpg") and rows["d"] is None, "a file fetched again takes its row over; a copy not kept leaves no path", rows)
    # the date of a saved file
    target = root / "dated.jpg"
    target.write_bytes(b"x")
    sync._stamp(target, "2024-03-05T10:20:30Z")
    check(int(os.path.getmtime(target)) == 1709634030, "a saved file carries its post's date", os.path.getmtime(target))
    sync._stamp(target, "2999-01-01T00:00:00Z")
    sync._stamp(target, "")
    check(int(os.path.getmtime(target)) == 1709634030, "no date, or one in the future, leaves the time as it was")
    # the time of a file: the post's date, else the listing's order among the posts around it
    import calendar
    T0 = 1709634030.0
    check(sync._post_time("2024-03-05T10:20:30Z") == T0 and sync._post_time("2024-03-05T19:20:30+0900") == T0 and sync._post_time("2024-03-05T19:20:30+09") == T0
          and sync._post_time("2024-03-05T10:20:30.1234567Z") == T0 + 0.123456 and sync._post_time("2024-03-05 10:20:30") == T0
          and sync._post_time("2024-03-05") == T0 - 37230 and sync._post_time("") is None and sync._post_time("soon") is None
          and sync._post_time("2999-01-01T00:00:00Z") is None, "a post's date is read in every form the sites write it (also on Python 3.10)")
    SRC = {"id": 1}
    mk = lambda key, posted="": types.SimpleNamespace(remote_key=key, post_url="", posted=posted)

    def stamps(card, saved, listing, fresh, newkeys=()):
        """saved: key -> (stamp, path); listing: keys newest first; fresh: the keys to download. The times of the fresh ones, in the listing's order."""
        with db.connect() as con:
            con.execute("DELETE FROM files WHERE artist_id = ?", (card,))
            for key, (st, path) in saved.items():
                con.execute("INSERT INTO files (artist_id, remote_key, path, stamp) VALUES (?, ?, ?, ?)", (card, key, path, st))
        media = {k: mk(k, dict(newkeys).get(k, "")) for k in listing}
        todo = [(SRC, None, media[k]) for k in listing if k in fresh]
        got = sync._timeline(card, todo, {1: [media[k] for k in listing]})
        return [round(got[(1, k)] - time.time(), 2) for k in listing if k in fresh]      # (seconds from now)
    with db.connect() as con:
        con.execute("INSERT OR IGNORE INTO artists (id, name) VALUES (7, 'Artist C')")
    first = stamps(7, {}, list("abcde"), set("abcde"))
    check(all(x > y for x, y in zip(first, first[1:])) and abs(first[0]) < 5 and abs(first[0] - first[1] - sync.STEP) < 0.01,
          "the first download of undated posts: the newest on top, STEP apart, the first of them now", first)
    news = stamps(7, {"s1": (time.time() - 100, "x"), "s2": (time.time() - 102, "x")}, ["n1", "n2", "n3", "s1", "s2"], {"n1", "n2", "n3"})
    check(all(x > y for x, y in zip(news, news[1:])) and min(news) > -100 + 1, "new posts above the newest saved file, in the listing's order", news)
    close = stamps(7, {"s1": (time.time() - 6, "x")}, ["n%d" % i for i in range(10)] + ["s1"], {"n%d" % i for i in range(10)})
    check(all(x > y for x, y in zip(close, close[1:])) and min(close) > -6 and max(close) < 3, "... squeezed in when the newest saved file is only seconds old", close)
    tail = stamps(7, {"s1": (time.time() - 100, "x"), "s2": (time.time() - 102, "x")}, ["s1", "s2", "t1", "t2", "t3"], {"t1", "t2", "t3"})
    check(all(x > y for x, y in zip(tail, tail[1:])) and max(tail) < -102, "the older tail of a cancelled or cut-off run goes BELOW what the first run saved", tail)
    mid = stamps(7, {"s1": (time.time() - 100, "x"), "s3": (time.time() - 110, "x")}, ["s1", "f1", "s3"], {"f1"})
    check(-110 < mid[0] < -100, "a file that failed and comes later goes back between its neighbours", mid)
    back = stamps(7, {"r1": (time.time() - 500, "/gone/r1.jpg"), "s1": (time.time() - 100, "x")}, ["s1", "r1"], {"r1"})
    check(abs(back[0] + 500) < 0.1, "a file fetched again after its folder was deleted gets the time it had", back)
    tie = stamps(7, {}, ["p1", "p2", "p3", "q1"], {"p1", "p2", "p3", "q1"}, [(k, "2024-03-05T10:20:30Z") for k in ("p1", "p2", "p3")])
    check(tie[0] > tie[1] > tie[2] > tie[3] and (tie[0] - tie[2]) < 0.5 and abs(tie[0] - (T0 - time.time())) < 0.01, "the images of one post: listing order kept a few milliseconds apart", tie)
    mixed = stamps(7, {}, ["u1", "d1", "u2", "u3"], {"u1", "d1", "u2", "u3"}, [("d1", "2024-03-05T10:20:30Z")])
    check(abs(mixed[1] - (T0 - time.time())) < 0.01 and mixed[0] > mixed[1] and mixed[2] == round(mixed[1] - sync.STEP, 2) and mixed[3] == round(mixed[1] - 2 * sync.STEP, 2),
          "undated posts sit between their dated neighbours in the listing's order", mixed)
    # the time is kept on the row, and a saved file is stamped through the real path (_fetch)
    class Cdn(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = jpeg((10, 120, 200), (64, 48))
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    base = serve(Cdn)
    lib = root / "Fetched"
    card = {"id": 7, "name": "Artist C", "folder": str(lib), "layout": "together", "dedupe": "keep_all", "master_source_id": None}
    site = types.SimpleNamespace(LABEL="Test")
    cur = {"failed": 0, "new": 0, "duplicates": 0, "existing": 0, "file": "", "size": 0}
    with db.connect() as con:
        con.execute("DELETE FROM files WHERE artist_id = 7")
    ok = sync._fetch(card, {"id": None, "url": base + "/m"}, site, Media(remote_key="t:1", url=base + "/1.jpg", post_url="p", posted="", name="one"), cur, 1500000000.0)
    ok2 = sync._fetch(card, {"id": None, "url": base + "/m"}, site, Media(remote_key="t:2", url=base + "/2.jpg", post_url="p", posted="2020-05-01T12:00:00Z", name="two"), cur)
    with db.connect() as con:
        saved = {r["remote_key"]: (r["path"], r["stamp"]) for r in con.execute("SELECT remote_key, path, stamp FROM files WHERE artist_id = 7")}
    check(ok is True and ok2 is True and os.path.getmtime(saved["t:1"][0]) == 1500000000.0 and saved["t:1"][1] == 1500000000.0
          and int(os.path.getmtime(saved["t:2"][0])) == calendar.timegm((2020, 5, 1, 12, 0, 0)) and saved["t:2"][1] == os.path.getmtime(saved["t:2"][0]),
          "a downloaded file is stamped in _fetch (the time given, else its post's date) and the row keeps it", saved)
    # restamp: Sourcerer's own untouched files get their post's date; an adopted or edited one keeps its time
    mine, adopted = lib / "mine.jpg", lib / "adopted.jpg"
    mine.write_bytes(b"x")
    adopted.write_bytes(b"x")
    os.utime(adopted, (1400000000, 1400000000))
    with db.connect() as con:
        con.execute("DELETE FROM files WHERE artist_id = 7")
        con.execute("DELETE FROM settings WHERE key = 'file_times_v1'")
        for key, path in (("m", mine), ("a", adopted)):
            con.execute("INSERT INTO files (artist_id, remote_key, path, posted) VALUES (7, ?, ?, '2021-01-02T03:04:05Z')", (key, str(path)))
    sync.restamp()
    want = calendar.timegm((2021, 1, 2, 3, 4, 5))
    check(int(os.path.getmtime(mine)) == want and os.path.getmtime(adopted) == 1400000000 and db.get_setting("file_times_v1") == "1",
          "restamp dates the files Sourcerer saved and leaves an adopted or edited file alone", (os.path.getmtime(mine), os.path.getmtime(adopted)))
    # "Put in upload order": the set of times is handed out again in the listing's order; dated posts get their date
    files = []
    for i in range(4):
        f = lib / ("o%d.jpg" % i)
        f.write_bytes(b"x")
        os.utime(f, (1600000000 + [30, 10, 40, 20][i], 1600000000 + [30, 10, 40, 20][i]))        # saved in a random order
        files.append(f)
    with db.connect() as con:
        con.execute("DELETE FROM files WHERE artist_id = 7")
        for i, f in enumerate(files):
            con.execute("INSERT INTO files (artist_id, remote_key, path) VALUES (7, ?, ?)", ("o%d" % i, str(f)))
    listing = [mk("o2"), mk("o0"), mk("o3"), mk("o1")]                                              # newest first
    sync._ordered({"id": 7, "name": "Artist C"}, {1: {"looked": True, "order": listing}}, {"artist_id": 7}, set())
    got = [os.path.getmtime(files[i]) - 1600000000 for i in (2, 0, 3, 1)]
    check(got == [40, 30, 20, 10], "Put files in upload order: the same times, the latest on the newest listed post", got)
    mk_dated = [mk("o2", "2022-02-02T00:00:00Z"), mk("o0", "2022-02-02T00:00:00Z"), mk("o3", "2022-01-01T00:00:00Z"), mk("o1")]
    sync._ordered({"id": 7, "name": "Artist C"}, {1: {"looked": True, "order": mk_dated}}, {"artist_id": 7}, set())
    d2, d0, d3 = (os.path.getmtime(files[i]) for i in (2, 0, 3))
    check(d2 > d0 > d3 and d2 - d0 < 0.1 and int(d2) == calendar.timegm((2022, 2, 2, 0, 0, 0)), "... and a dated post's files get its date, the images of one post apart", (d2, d0, d3))
    check(sync._long("a/b") == os.path.abspath("a/b"), "a path that is not long is left as it is")
    shutil.rmtree(root, ignore_errors=True)


def refresh_checks():
    from sourcerer import follows, sync
    calls = []
    real = follows.look_async, sync.enqueue
    follows.look_async = lambda only=None: calls.append(("follows", only))
    sync.enqueue = lambda *a, **k: calls.append(("enqueue", k.get("mode"))) or 0
    try:
        client = server.app.test_client()

        def asked(body):
            calls.clear()
            status = client.post("/api/sync", json=body).status_code
            return status, [c[0] for c in calls]
        everyone = asked({"order": [1, 2]})
        one = asked({"artist_id": 1})
        download = asked({"mode": "download"})
        arranged = asked({"artist_id": 1, "mode": "order"})
    finally:
        follows.look_async, sync.enqueue = real
    check(everyone == (200, ["follows", "enqueue"]), "Refresh all also looks at the accounts every login follows", everyone)
    check(one == (200, ["enqueue"]) and arranged == (200, ["enqueue"]), "one card's Refresh reads that card and its sources only", (one, arranged))
    check(download == (200, ["enqueue"]), "a download of the cards that download reads no follow list", download)


def cooling_checks():
    import datetime
    from sourcerer import config, gallery, sync
    def ago(hours):
        return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    for url in ("https://www.pixiv.net/users/1", "https://bsky.app/profile/a.bsky.social"):          # a cookie login's site and an open one: the same rule
        check(sync._cooling({"looked_at": ago(11), "url": url, "latest": ago(24 * 400)}, True),
              "a sweep leaves a source read 11 hours ago alone (%s)" % url.split("/")[2])
        check(not sync._cooling({"looked_at": ago(13), "url": url, "latest": ago(1)}, True), "... and reads it again after twelve hours (%s)" % url.split("/")[2])
    check(not sync._cooling({"looked_at": ago(1), "url": "https://x.com/a", "latest": None}, False), "a card asked for by name is never held back")
    check(not sync._cooling({"looked_at": None, "url": "https://x.com/a", "latest": None}, True), "a source never read has no gap")
    check(sync.COOL_HOURS * 3600 == gallery.FRESH_ARTIST, "an artist opened on its own is left alone as long as a sweep leaves it", (sync.COOL_HOURS, gallery.FRESH_ARTIST))
    check(config.DEFAULTS["scan_on_start"] == "1", "the scan at every start is on by default")


def main():
    for group in (forum_checks, tile_checks, speed_checks, refusal_checks, tune_checks, settings_checks, gallery_checks, media_checks, poipiku_checks, resume_checks, library_checks, cooling_checks, refresh_checks):
        print("--", group.__name__, flush=True)
        try:
            group()
        except Exception as e:                    # a check that cannot run is a failed check
            import traceback
            traceback.print_exc()
            check(False, "%s ran to its end" % group.__name__, e)
    shutil.rmtree(WORK, ignore_errors=True)
    print("")
    print("%d check(s) failed: %s" % (len(FAILS), "; ".join(FAILS)) if FAILS else "all checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
