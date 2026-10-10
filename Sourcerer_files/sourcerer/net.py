"""HTTP with the standard library: JSON requests and streamed downloads.

No requests/httpx: two calls do not justify a dependency, and every package
is one more thing the launcher has to install on three systems.
"""
import hashlib
import json
import logging
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger(__name__)
TIMEOUT = 60
RETRIES = 3

# Extensions for the content types sites actually send, so a file whose URL
# has none (Mastodon's ".../original", Bluesky's getBlob) still opens properly.
_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
        "image/webp": ".webp", "image/avif": ".avif", "image/heic": ".heic",
        "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
        "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/mp4": ".m4a"}


def _open(url, params=None):
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url += ("&" if "?" in url else "?") + query
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    for attempt in range(RETRIES):
        try:
            return urllib.request.urlopen(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            # 429 and 5xx pass with time; anything else will not.
            if e.code != 429 and e.code < 500 or attempt == RETRIES - 1:
                raise
            wait = e.headers.get("Retry-After", "")
            time.sleep(min(int(wait), 120) if wait.isdigit() else 5 * (attempt + 1))
        except urllib.error.URLError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(5 * (attempt + 1))


def get_json(url, params=None):
    with _open(url, params) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extension(content_type, url="", fallback=".bin"):
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in _EXT:
        return _EXT[ctype]
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if 1 < len(ext) <= 5:
        return ext
    return mimetypes.guess_extension(ctype) or fallback


def download(url, folder, mime_hint=""):
    """Stream url into folder/<random>.part; returns (part_path, sha256, extension)."""
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (".%s.part" % os.urandom(6).hex())
    digest = hashlib.sha256()
    try:
        with _open(url) as resp, open(part, "wb") as out:
            ext = extension(resp.headers.get("Content-Type") or mime_hint, url)
            for chunk in iter(lambda: resp.read(1 << 16), b""):
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return part, digest.hexdigest(), ext
