"""The newest posts of a source, as the last look at it left them.

Every look at a source's first page -- a sync, the card previews' worker, Browse -- keeps what
it found here: the Media objects themselves (pickled: a few hundred bytes each; a pixiv work
carries the function that resolves its original), newest first, at most KEEP of them. Browse
then opens from this at once and checks the site meanwhile (gallery._Source), a card counts
what is new without asking anybody, and the previews need no listing of their own.

It is the program's own data in its own database, yet the database travels with Userdata: a
snapshot is read back through an unpickler that builds only Sourcerer's own classes and
functions (and functools.partial), nothing else. One made by a version whose Media looked
different is dropped (SHAPE), not guessed at.
"""
import dataclasses
import datetime
import functools
import importlib
import io
import logging
import pickle
import sqlite3

from . import db
from .sources import Media

log = logging.getLogger(__name__)
KEEP = 60                    # posts kept per source
SHAPE = ",".join(f.name for f in dataclasses.fields(Media))


class _Reader(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) == ("functools", "partial"):
            return functools.partial
        # A function or class that Sourcerer's own source modules define -- not what they import
        # (os, subprocess ...), and no dotted names that would reach it.
        if module.startswith("sourcerer.sources") and "." not in name:
            obj = getattr(importlib.import_module(module), name, None)
            if callable(obj) and getattr(obj, "__module__", None) == module:
                return obj
        raise pickle.UnpicklingError("%s.%s is not kept in a snapshot" % (module, name))


def save(source_id, items, merge=True):
    """Keep these (newest first) as the source's snapshot; nothing found keeps what was there.
    merge: a look at one short page does not throw away what an earlier, longer one kept --
    the older posts of the snapshot follow the new ones, up to KEEP."""
    items = list(items)
    if not items:
        return
    if merge:
        old = load(source_id)
        if old:
            have = {m.remote_key for m in items}
            items += [m for m in old[1] if m.remote_key not in have]
    items = items[:KEEP]
    try:
        blob = pickle.dumps((SHAPE, items), protocol=4)
    except Exception as e:                      # a Media with something that cannot be kept
        log.info("snapshot of source %s not kept: %s", source_id, e)
        return
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with db.connect() as con:
            con.execute("INSERT INTO snapshots (source_id, fetched, data) VALUES (?, ?, ?) "
                        "ON CONFLICT (source_id) DO UPDATE SET fetched = excluded.fetched, data = excluded.data",
                        (source_id, now, blob))
    except sqlite3.IntegrityError:               # the source was removed meanwhile
        pass


def load(source_id):
    """(when it was made as a Unix time, [Media newest first]) or None."""
    with db.connect() as con:
        row = con.execute("SELECT fetched, data FROM snapshots WHERE source_id = ?", (source_id,)).fetchone()
    if not row:
        return None
    try:
        shape, items = _Reader(io.BytesIO(row["data"])).load()
        if shape != SHAPE:
            return None
        return datetime.datetime.fromisoformat(row["fetched"]).timestamp(), items
    except Exception as e:
        log.info("snapshot of source %s unreadable: %s", source_id, e)
        return None
