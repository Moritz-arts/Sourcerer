"""gallery-dl's entry point for Sourcerer's reads of X's follows (`_gdl.info(..., verbose=True)`).

Plain `gallery-dl` when SOURCERER_GDL_TRACE is not set. When it is "limits" -- the listings of X, Fanbox and Fantia that Sourcerer
counts -- one thing is added: the rate limit X announces on its answers goes to stderr (`[sourcerer][limit] UserMedia 50 47 <reset>`:
what it allows, what is left, when it resets), which is how Sourcerer learns what X really allows an account. When it is "1" -- only
the two runs that read who the login follows -- two more things are added, both on gallery-dl's own X client (`TwitterAPI`):

* what X's answers look like, on stderr (`[sourcerer][trace] Following {...}`): the keys, the kinds of values and the types of
  entries, never a value that is somebody's (a name, an id, a number) -- v0.38 and v0.39 got HTTP 200 and no follows from X and
  nothing said why;
* a way round gallery-dl's own reading of a list of users: it looks for them at one place and ends quietly when X moved them
  (the KeyError in `_pagination_users`). Users are looked for anywhere in the answer, and the page after it by the bottom cursor.

When it is "xenforo" -- the listings of a forum's media -- only one thing is added (`xenforo()`): the date each picture's tile shows in
the list page is handed to gallery-dl's own record of the picture (`date`), which it throws away without `metadata` (one more
request per picture).

Standalone on purpose: it imports nothing of Sourcerer, so it runs as a script (`python gdl_run.py ...`) and, in the one-file
build, from app.py's `--gallery-dl` before anything else is loaded.
"""
import json
import os
import re
import sys

TRACE = "SOURCERER_GDL_TRACE"
SHOWN = ("type", "__typename", "entryId", "cursorType", "entryType", "itemType", "code")   # values worth seeing: kinds, not data
PAGES = 40                       # pages of users the way round reads at most


def _kind(entry):
    return re.sub(r"[-_]?\d{4,}.*", "", str(entry.get("entryId")))[:40]            # "tweet-123..." -> "tweet", "cursor-top-17..." -> "cursor-top"


def _outline(x, depth=0, key=""):
    """The shape of an answer: keys, how many in a list and what its first has, the kind of every value.
    A list of timeline entries is told by its kinds (what is in the timeline: tweets, users, only cursors), a list of
    instructions by every one of them -- the first of four said nothing in v0.40."""
    if isinstance(x, list) and x and all(isinstance(i, dict) and "entryId" in i for i in x):
        return {"entries": [_kind(i) for i in x[:24]], "count": len(x)}
    if isinstance(x, list) and key == "instructions" and all(isinstance(i, dict) for i in x):
        return [_outline(i, depth + 1, key) for i in x[:8]]
    if isinstance(x, dict):
        if depth > 12:
            return "{%d}" % len(x)
        return {k: _outline(v, depth + 1, k) for k, v in list(x.items())[:16]}
    if isinstance(x, list):
        return ["%d x" % len(x), _outline(x[0], depth + 1, key)] if x else []
    if key == "message" and isinstance(x, str):
        return x[:100]                                           # an error's text ("Dependency: Unspecified")
    if key in SHOWN and isinstance(x, (str, int)):
        return re.sub(r"\d{4,}.*", "#", x)[:40] if isinstance(x, str) else x
    return type(x).__name__


def _say(name, what):
    sys.stderr.write("[sourcerer][trace] %s %s\n" % (name, json.dumps(what, separators=(",", ":"))[:3500]))
    sys.stderr.flush()


def _users_anywhere(node, seen):
    """The users in an answer, wherever X put them: a dict with a rest_id and a core or legacy part."""
    if isinstance(node, dict):
        if "rest_id" in node and ("core" in node or "legacy" in node) and node.get("__typename") != "UserUnavailable":
            if node["rest_id"] not in seen:
                seen.add(node["rest_id"])
                yield node
            return
        for value in node.values():
            yield from _users_anywhere(value, seen)
    elif isinstance(node, list):
        for value in node:
            yield from _users_anywhere(value, seen)


def _bottom_cursor(node):
    if isinstance(node, dict):
        if node.get("cursorType") == "Bottom" and isinstance(node.get("value"), str):
            return node["value"]
        for value in node.values():
            found = _bottom_cursor(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _bottom_cursor(value)
            if found:
                return found
    return None


def limits():
    """X's answers carry x-rate-limit-limit / -remaining / -reset for the endpoint asked: said on stderr, one line per answer."""
    from gallery_dl.extractor import common
    plain = common.Extractor.request

    def request(self, url, *args, **kwargs):
        response = plain(self, url, *args, **kwargs)
        try:
            h = response.headers
            if "x-rate-limit-remaining" in h:
                sys.stderr.write("[sourcerer][limit] %s %s %s %s\n" % (
                    url.split("?", 1)[0].rsplit("/", 1)[-1] or "?", h.get("x-rate-limit-limit", "0"),
                    h["x-rate-limit-remaining"], h.get("x-rate-limit-reset", "0")))
                sys.stderr.flush()
        except Exception:
            pass
        return response

    common.Extractor.request = request


def install():
    from gallery_dl.extractor import twitter
    api = twitter.TwitterAPI
    plain_call, plain_users = api._call, api._pagination_users

    def call(self, endpoint, params, *args, **kwargs):
        data = plain_call(self, endpoint, params, *args, **kwargs)
        self._sourcerer_pages = getattr(self, "_sourcerer_pages", [])[-60:] + [data]          # every answer of this read, for users()
        try:
            name = endpoint.rsplit("/", 1)[-1]
            _say(name, _outline(data))
            if name == "UserByRestId":                           # who the login is, and how many accounts X says it follows
                user = data["data"]["user"]["result"]
                _say("account", {"screen_name": user["core"]["screen_name"], "follows": user["legacy"]["friends_count"],
                                 "followers": user["legacy"]["followers_count"]})
        except Exception:
            pass
        return data

    def users(self, *args, **kwargs):                            # (any signature a newer gallery-dl may have: only the recovery below needs the first two)
        mark = len(getattr(self, "_sourcerer_pages", []))
        found = 0
        for user in plain_users(self, *args, **kwargs):
            found += 1
            yield user
        if found:
            return
        # gallery-dl found none in the answers it was given: look for users anywhere in them -- every page it read, not
        # only the last -- and go on by the bottom cursor of the last
        try:
            endpoint, variables = args[0], args[1]
            seen, pages = set(), list(getattr(self, "_sourcerer_pages", []))[mark:]
            for data in pages:
                yield from _users_anywhere(data, seen)
            data = pages[-1] if pages else None
            for _ in range(PAGES):
                cursor = _bottom_cursor(data) if data else None
                if not cursor or cursor.startswith(("-1|", "0|")):
                    break
                variables["cursor"] = cursor
                data = self._call(endpoint, {"variables": self._json_dumps(variables),
                                             "features": self._json_dumps(self.features_pagination)})
                got = list(_users_anywhere(data, seen))
                yield from got
                if not got:
                    break
            if seen:
                _say("users", "%d found outside the place gallery-dl looks" % len(seen))
        except Exception as e:                                   # a gallery-dl that changed: as if the recovery was not there
            _say("users", "recovery failed: %s" % e)

    api._call, api._pagination_users = call, users


# One tile of a forum's media list, as gallery-dl cuts them (the same marker it splits the page at): the address of the picture's page,
# then somewhere in the tile the time it was made as XenForo writes it, <time ... datetime="2020-05-01T12:00:00+0000">.
TILE = '<div class="itemList-item js-inlineModContainer'
TILE_LENGTH = 2500                                    # a tile that never closes (broken markup) is read this far
TIME = re.compile(r"<time\b[^>]*?\bdatetime=[\"']([^\"']+)[\"']", re.I)
HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)
DIV = re.compile(r"<(/?)div\b", re.I)


def tile_of(text):
    """What a tile holds: from the end of its marker to the </div> that closes it. The last tile of a page is followed by the page's own
    furniture -- a footer, a "latest" box -- and its times (today's, mostly) were taken for the picture's: every last tile of a page got one."""
    depth = 1                                           # the marker is the tile's opening <div>
    for m in DIV.finditer(text, 0, TILE_LENGTH * 4):
        depth += -1 if m.group(1) else 1
        if not depth:
            return text[:m.start()]
    return text[:TILE_LENGTH]


def tile_dates(page, dates):
    """{slug: datetime text} of the tiles of a list page -- "title.123" is how gallery-dl names the picture (the last part of its address).
    A tile that shows no time of its own gives none."""
    for tile in page.split(TILE)[1:]:
        tile = tile_of(tile)
        href, when = HREF.search(tile), TIME.search(tile)
        if href and when:
            dates[href.group(1).rstrip("/").rsplit("/", 1)[-1]] = when.group(1)


def xenforo():
    """Dates for the pictures of a forum's media list. gallery-dl reads each tile's address and alt text and nothing else; its pages go
    through `_pagination`, which is wrapped to read the tiles' times on their way, and the record it makes of a picture
    (`_extract_media`) gets the time of its tile as `date`. Any change of gallery-dl that breaks this leaves it as it was (no date).
    The extractor's module is imported only once gallery-dl has read its config: it builds the pattern of the forums it answers for from
    the instances the config names (Sourcerer's own, registered by sources/xenforo.py), and a module imported before that knows none."""
    from gallery_dl import config
    plain_load = config.load

    def load(*args, **kwargs):
        done = plain_load(*args, **kwargs)
        try:
            wrap_xenforo()
        except Exception as e:
            sys.stderr.write("[sourcerer][trace] xenforo dates not installed: %s\n" % e)
        return done

    config.load = load


def wrap_xenforo():
    from gallery_dl.extractor import xenforo as module
    cls, dates = module.XenforoExtractor, {}

    def paged(plain):
        def pages(self, *args, **kwargs):
            for page in plain(self, *args, **kwargs):
                try:
                    tile_dates(page, dates)
                except Exception:
                    pass
                yield page
        return pages

    plain_media = cls._extract_media

    def media(self, url, file, *args, **kwargs):
        found = plain_media(self, url, file, *args, **kwargs)
        try:
            if dates.get(file) and isinstance(found, tuple) and isinstance(found[1], dict):
                found[1]["date"] = dates[file]
        except Exception:
            pass
        return found

    cls._pagination = paged(cls._pagination)
    if hasattr(cls, "_pagination_reverse"):
        cls._pagination_reverse = paged(cls._pagination_reverse)
    cls._extract_media = media


def main():
    mode = os.environ.get(TRACE)
    if mode:
        try:
            if mode == "xenforo":
                xenforo()
            else:
                limits()
                if mode != "limits":
                    install()
        except Exception as e:                                   # a gallery-dl that changed: plain, as before
            sys.stderr.write("[sourcerer][trace] not installed: %s\n" % e)
    import gallery_dl
    return gallery_dl.main()


if __name__ == "__main__":
    sys.argv[0] = "gallery-dl"
    sys.exit(main())
