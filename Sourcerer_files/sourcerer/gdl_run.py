"""gallery-dl's entry point for Sourcerer's reads of X's follows (`_gdl.info(..., verbose=True)`).

Plain `gallery-dl` when SOURCERER_GDL_TRACE is not set. When it is set -- only the two runs that read who the login follows --
two things are added, both on gallery-dl's own X client (`TwitterAPI`):

* what X's answers look like, on stderr (`[sourcerer][trace] Following {...}`): the keys, the kinds of values and the types of
  entries, never a value that is somebody's (a name, an id, a number) -- v0.38 and v0.39 got HTTP 200 and no follows from X and
  nothing said why;
* a way round gallery-dl's own reading of a list of users: it looks for them at one place and ends quietly when X moved them
  (the KeyError in `_pagination_users`). Users are looked for anywhere in the answer, and the page after it by the bottom cursor.

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


def _outline(x, depth=0, key=""):
    """The shape of an answer: keys, how many in a list and what its first has, the kind of every value."""
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


def install():
    from gallery_dl.extractor import twitter
    api = twitter.TwitterAPI
    plain_call, plain_users = api._call, api._pagination_users

    def call(self, endpoint, params, *args, **kwargs):
        data = plain_call(self, endpoint, params, *args, **kwargs)
        self._sourcerer_last = data
        try:
            _say(endpoint.rsplit("/", 1)[-1], _outline(data))
        except Exception:
            pass
        return data

    def users(self, endpoint, variables, path=None):
        found = 0
        for user in plain_users(self, endpoint, variables, path):
            found += 1
            yield user
        if found:
            return
        # gallery-dl found none in the answer it was given: look for users anywhere in it, page after page
        seen, data = set(), getattr(self, "_sourcerer_last", None)
        for _ in range(PAGES):
            got = list(_users_anywhere(data, seen)) if data else []
            yield from got
            cursor = _bottom_cursor(data) if data else None
            if not got or not cursor or cursor.startswith(("-1|", "0|")):
                break
            variables["cursor"] = cursor
            data = self._call(endpoint, {"variables": self._json_dumps(variables),
                                         "features": self._json_dumps(self.features_pagination)})
        if seen:
            _say("users", "%d found outside the place gallery-dl looks" % len(seen))

    api._call, api._pagination_users = call, users


def main():
    if os.environ.get(TRACE):
        try:
            install()
        except Exception as e:                                   # a gallery-dl that changed: plain, as before
            sys.stderr.write("[sourcerer][trace] not installed: %s\n" % e)
    import gallery_dl
    return gallery_dl.main()


if __name__ == "__main__":
    sys.argv[0] = "gallery-dl"
    sys.exit(main())
