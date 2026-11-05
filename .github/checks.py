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
* gallery.picture for a site with no resolver (the booru-like case the forum fix must not change).

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
from sourcerer.sources import Media, xenforo                                 # noqa: E402

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
MODE = {"anchors": True, "same_ids": False, "hits": []}


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
    return "<html><body>" + post(501, [9001, 9002]) + post(502, [], inline=[9003]) + "</body></html>"


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
    need = {"parallel", "per_host", "pause", "gap", "pace", "files", "every", "rest", "look", "preview", "browse"}
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
    check(got[0] == 1.0 and got[1] == (40, 80) and got[2] == (6, 20), "normal files: 1.0 s, a rest of 6-20 s every 40-80", got)
    check(net._rhythm(site_url, False)[0] == 2.0, "a page keeps LOGIN_PACE whatever is chosen")
    net.configure(speed="fast")
    got = net._rhythm(site_url, True)
    check(got[0] == 0.5 and got[1] is None, "fast files: 0.5 s, no rest", got)
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
        for name, least in (("normal", 0.1), ("fast", 0.05)):
            fresh(name)
            starts, peak = lane(site_url, 4, 0.05, bulk=True)
            gaps = [b - a for a, b in zip(starts, starts[1:])]
            check(peak == 1 and all(g >= least - 0.01 for g in gaps), "%s: files one at a time, %.2f s after the end of the last" % (name, least), (peak, gaps))
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
    state = client.get("/api/state?speed=full").get_json()["speed"]
    names = {k["key"] for k in state["knobs"]}
    want = {"parallel", "per_host", "pause", "pace", "files", "every", "rest", "gap_min", "gap_max", "look", "preview_n", "browse_n",
            "limit_pixiv", "limit_patreon", "limit_x", "limit_fanbox", "limit_fantia", "limit_other"}
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
    got = client.put("/api/speed", json={"tune": {"parallel": 999, "pace": 0.01, "per_host": 24, "pause": 0.1}}).get_json()["speed"]["values"]
    check(got["parallel"] == 64 and got["pace"] == 0.5 and got["per_host"] == 24 and "pause" not in net.tuning(),
          "a value is clamped into its range; one that equals the level's is no change", (got, net.tuning()))
    before = net.tuning()
    check(client.put("/api/speed", json={"tune": {"files": "soon"}}).status_code == 400 and net.tuning() == before, "a value that is no number is refused and changes nothing")
    client.put("/api/speed", json={"tune": {"gap_min": 20, "gap_max": 5}})
    check(net.profile()["gap"] == (20, 20) and net.tuning().get("gap_max") == 20, "a gap's end below its start is raised where the page sees it", net.tuning())
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
    state = client.get("/api/state?speed=full").get_json()
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


def main():
    for group in (forum_checks, tile_checks, speed_checks, refusal_checks, tune_checks, settings_checks, gallery_checks):
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
