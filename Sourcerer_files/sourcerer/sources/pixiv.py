"""Pixiv. Public works need no login; R-18 works are listed only to a logged-in
account that has R-18 switched on in its pixiv settings -- logged out, pixiv
leaves them out of the list altogether, so nothing even fails.

Lists come from the JSON pixiv's own pages read (www.pixiv.net/ajax/...):
user/<id>/profile/all names every work id at once (higher id = newer),
user/<id>/profile/illusts gives up to 48 of them per request with date, type
and page count, illust/<id>/pages the original of every page. The originals
are on i.pximg.net, which answers 403 without a Referer from pixiv.

Asking /pages for every work while scanning would cost one request per work
before anything downloads, and again on every sync for works already saved.
So a work's files are only listed while scanning (its page count is known) and
the original's address is asked for when the file is fetched (Media.fetch).

pixiv's terms forbid "large numbers of actions within a short period": net.py
keeps www.pixiv.net at one request at a time, 1.5 s apart, and stops at the
first 429; MAX_NEW spreads a big first sync over several.
"""
import functools
import hashlib
import io
import os
import re
import threading
import urllib.parse

import requests

from .. import net

KIND = "pixiv"
LABEL = "Pixiv"
MAX_NEW = 500
AJAX = "https://www.pixiv.net/ajax/"
REFERER = {"Referer": "https://www.pixiv.net/"}
PAGE = 48            # what pixiv's own profile page asks for; the endpoint refuses 200
UGOIRA = 2           # illustType: 0 illustration, 1 manga, 2 ugoira (animation)
_USER = re.compile(r"^https?://(?:www\.|touch\.)?pixiv\.net/(?:[a-z]{2}/)?"
                   r"(?:users/|u/|member(?:_illust)?\.php\?(?:[^#]*&)?id=)(\d+)", re.I)
_OTHER = re.compile(r"^https?://(?:(?:www\.)?pixiv\.net/(?:[a-z]{2}/)?artworks/(\d+)"
                    r"|pixiv\.me/([\w-]+))", re.I)


def match(url):
    url = url.strip()
    return bool(_USER.match(url) or _OTHER.match(url))


def _uid(url):
    return _USER.match(url.strip()).group(1)


def normalize(url):
    """https://www.pixiv.net/users/<id>, also from a work's link or a pixiv.me name."""
    m = _OTHER.match(url.strip())
    if m and m.group(1):
        uid = _ajax("illust/%s" % m.group(1))["userId"]
    elif m:
        uid = _uid(net.get_text(url)[1])                 # pixiv.me answers 301 -> /users/<id>
    else:
        uid = _uid(url)
    return "https://www.pixiv.net/users/%s" % uid


def _ajax(path, params=()):
    # A list of pairs, not a dict: ids[] repeats.
    pairs = list(params.items() if isinstance(params, dict) else params) + [("lang", "en")]
    try:
        data = net.get_json(AJAX + path + "?" + urllib.parse.urlencode(pairs))
    except requests.HTTPError as e:
        # An expired session answers 401 "An unknown error occurred".
        if e.response is not None and e.response.status_code == 401:
            from . import LoginRequired
            raise LoginRequired("pixiv: log in again") from e
        raise
    if data.get("error"):
        raise RuntimeError("pixiv: %s" % (data.get("message") or "request refused"))
    return data["body"]


def profile(url):
    uid = _uid(url)
    user = _ajax("user/%s" % uid)
    return {"name": user.get("name") or uid, "handle": "pixiv.net/users/%s" % uid,
            "avatar": user.get("imageBig") or user.get("image") or "",
            "avatar_headers": REFERER}


def pages(url):
    uid = _uid(url)
    every = _ajax("user/%s/profile/all" % uid)
    ids = sorted({int(i) for kind in ("illusts", "manga") for i in (every.get(kind) or {})},
                 reverse=True)
    for start in range(0, len(ids), PAGE):
        chunk = ids[start:start + PAGE]
        works = _ajax("user/%s/profile/illusts" % uid, [("ids[]", i) for i in chunk] + [
            ("work_category", "illustManga"), ("is_first_page", int(start == 0))])["works"]
        page = []
        for wid in chunk:
            work = works.get(str(wid))
            if work:                              # deleted between the two requests
                page += _media(work)
        yield page


def _media(work):
    from . import Media
    wid, post = work["id"], "https://www.pixiv.net/artworks/%s" % work["id"]
    posted = work.get("createDate") or ""         # 2026-10-09T13:00:15+09:00
    if work.get("illustType") == UGOIRA:
        return [Media(remote_key="pixiv:%s_ugoira" % wid, url="", post_url=post, posted=posted,
                      name="%s_ugoira" % wid, mime="image/webp", local=["%s*_ugoira.webp" % wid],
                      fetch=functools.partial(_fetch_ugoira, wid))]
    return [Media(remote_key="pixiv:%s_p%d" % (wid, n), url="", post_url=post, posted=posted,
                  name="%s_p%d" % (wid, n), local=["%s_p%d.*" % (wid, n), "%s-*_p%d.*" % (wid, n)],
                  fetch=functools.partial(_fetch_page, wid, n))
            for n in range(int(work.get("pageCount") or 1))]


_lock = threading.Lock()


@functools.lru_cache(maxsize=256)
def _originals(wid):
    return tuple(p["urls"]["original"] for p in _ajax("illust/%s/pages" % wid))


def _original(wid, n):
    with _lock:            # one /pages request per work, though threads fetch its pages at once
        urls = _originals(wid)
    if n >= len(urls) or not urls[n]:
        raise RuntimeError("pixiv: page %d of work %s is gone" % (n, wid))
    return urls[n]


def _fetch_page(wid, n, folder, progress=None):
    url = _original(wid, n)
    part, sha, ext, _name = net.download(url, folder, "", progress, headers=REFERER)
    # The site's own name: 12345_p0.png, or 12345-<32 hex>_p0.jpg on newer works --
    # the hash cannot be guessed, so the name always comes from /pages.
    return part, sha, ext, url.rsplit("/", 1)[-1]


def _fetch_ugoira(wid, folder, progress=None):
    """The original frames as one lossless animated WebP with pixiv's delays.
    The ZIP pixiv offers holds recompressed frames; img-original has the real ones."""
    from PIL import Image
    meta = _ajax("illust/%s/ugoira_meta" % wid)
    # /pages names frame 0 with its real type; ugoira_meta's mime_type says jpeg for png and gif.
    base, _, ext = _original(wid, 0).rpartition("_ugoira0.")
    frames = []
    for i in range(len(meta["frames"])):
        data = net.fetch_bytes("%s_ugoira%d.%s" % (base, i, ext), limit=64 << 20, headers=REFERER)
        if progress:
            progress(len(data))
        frames.append(Image.open(io.BytesIO(data)))
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (".%s.part" % os.urandom(6).hex())
    frames[0].save(part, format="WEBP", save_all=True, append_images=frames[1:], lossless=True,
                   duration=[f["delay"] for f in meta["frames"]], loop=0)
    return (part, hashlib.sha256(part.read_bytes()).hexdigest(), ".webp",
            "%s_ugoira.webp" % base.rsplit("/", 1)[-1])
