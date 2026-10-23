"""The accounts a login follows, as artists in the list.

Logging in tells a site who you are, and the site knows whom you follow: Bluesky, Mastodon and
pixiv list that (`following(key)` in their modules, yielding (list name, pages of {"url", "name",
"avatar"})). Every followed account becomes a card -- once -- so the list fills itself and a source
needs no pasted link. Such a card is only *listed* (`artists.listed`): nothing reads its sites in
the background and nothing downloads until the user does something with it, because hundreds of
cards looked at by every sweep (the automatic sync) would be hundreds of requests nobody asked for.
(Refresh all only scans them -- the newest page -- and stops at half a day's requests. All artists
shows them, from the snapshots those looks saved; it never asks a login site, gallery._Source.seed.)

What is added is remembered (`followed`, by lower-cased profile URL), so a card the user deleted
does not come back and a card merged into another is not made again. A list read to its end once
by this login is read again only up to its first page of known accounts: the newest follows come
first, and the rest would be the same requests again for nothing.

The same artist is often followed on several sites, as accounts of one name. Those are put on one
card as they come in (`_Twins`), and the cards that are already apart are combined (`combine`): a
name is the same when only what is no letter or digit differs (emoji, spaces, width, case), and the
accounts must be on different sites -- two accounts of one name on one site are more likely two people.

The lists are the sites' words, not ours: a link is taken only when it is a profile of the list's
own site (never another site's address, which could cost a request on a login), and a picture only
from a public https address. A card keeps the address of the account's picture (`artists.avatar_url`) and
nothing else: the page shows it through /api/avatar, in memory.
"""
import collections
import json
import logging
import random
import re
import threading
import time
import unicodedata
import urllib.parse

from . import accounts, db, net, sources, sync

log = logging.getLogger(__name__)
HOURS = (10, 14)             # between two looks at the lists, while Sourcerer runs
version = 0                  # counts the changes the page should reload for (cards made, combined)
RETRY_HOURS = 4              # a costly list that failed is looked at again after this, not at the next ten to fourteen hours
_retry = False               # a look of the last round failed
_bumped = 0.0
_lock = threading.Lock()     # combining the cards: one at a time
_adding = threading.Lock()   # cards made from a page: one page at a time (the lists themselves are read side by side)
_reading = {}                # a login's list is read once at a time: key -> lock
_told_empty = set()           # logins whose empty list was said once, this run


def _touch(force=False):
    """The page reloads its list when this moves: at most every few seconds while a long list is read."""
    global version, _bumped
    if force or time.monotonic() - _bumped > 4:
        _bumped = time.monotonic()
        version += 1


def _site(key):
    return next((s for s in sources.SITES if s.KIND == key.split(":", 1)[0]), None)


def keys():
    """The saved logins that still work and whose site lists follows."""
    return [a["key"] for a in accounts.accounts()
            if a["logged_in"] and a["state"] != "expired" and getattr(_site(a["key"]), "following", None)]


def _name(f, url):
    name = " ".join((f.get("name") or "").split())[:200]
    return name or urllib.parse.unquote(urllib.parse.urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])


def _who(url):
    """What tells two accounts of one name apart: their handle."""
    parts = urllib.parse.urlsplit(url)
    last = urllib.parse.unquote(parts.path.rstrip("/").rsplit("/", 1)[-1]).lstrip("@")
    if parts.hostname in ("bsky.app", "bsky.social"):
        return last
    if parts.hostname and parts.hostname.endswith("pixiv.net"):
        return "pixiv " + last
    return last if "@" in last else "%s@%s" % (last, parts.hostname)


def _unique(name, url, taken):
    """A card's folder is its name: two accounts called Mochi must not share one."""
    cand, n = name, 1
    while sync.safe_name(cand).lower() in taken:
        n += 1
        cand = "%s (%s)" % (name, _who(url)) + (" %d" % n if n > 2 else "")
    taken.add(sync.safe_name(cand).lower())
    return cand


def name_key(name):
    """A name without what is no letter or digit, in one case and width: "👹 青林檎テル" is "青林檎テル".
    (The page's `nameKey` in app.js does the same for its suggestions: keep them alike.)"""
    return "".join(ch for ch in unicodedata.normalize("NFKC", name or "").casefold() if ch.isalnum())


def _base_key(name):
    """The same without a "(handle)" at the end, which a card gets when another had its name."""
    return name_key(re.sub(r"\s*[(\[（【][^)\]）】]*[)\]）】]\s*$", "", name or ""))


HANDLE_MIN = 4                           # an account name shorter than this says too little to join two cards by it
STEM_MIN = 5                             # ... and one without its trailing digits says it only from here
HANDLE_KINDS = ("x", "bluesky", "mastodon", "misskey", "patreon", "fanbox", "xenforo")     # sites whose address names the account, the best known first


_NOT_NAMES = {"index", "user", "users", "profile", "profiles", "members", "member", "u", "c", "media", "m", "creator"}


def handle_text(url):
    """The account's own name in its address, as written: "Mewnet" for mastodon.social/@Mewnet, x.com/Mewnet,
    bsky.app/profile/mewnet.bsky.social and mewnet.fanbox.cc -- what a display name ("Mew") is not. "" where the address
    names no account (pixiv's number, a booru's search, a forum routed through `index.php?media/users/name.12`, Patreon's
    `/user?u=1`, a Bluesky DID). `card_name` names the card by it."""
    kind = sources.kind_of(url)
    if kind not in HANDLE_KINDS:
        return ""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    # A forum that routes only through `index.php?` has the member in the query, not the path.
    where = parts.query if kind == "xenforo" and "/" in parts.query else parts.path
    last = host.split(".")[0] if host.endswith(".fanbox.cc") else \
        urllib.parse.unquote(where.rstrip("/").rsplit("/", 1)[-1])
    text = last.lstrip("@").split("@")[0].split(".")[0]
    key = name_key(text)
    return text if key and not key.isdigit() and ":" not in last and text.lower() not in _NOT_NAMES else ""


def handle_key(url):
    """The account name as a name key -- the surest thing two accounts of one artist share when the display names differ
    (an artist known by several names). Short ones say nothing: "". (`handlesOf` in app.js is its twin for the merge
    dialog's suggestions.)"""
    key = name_key(handle_text(url))
    return key if len(key) >= HANDLE_MIN else ""


def stem_of(url):
    """(the account name without the digits at its end, whether it had none) -- @Blackmoon, @blackmoon_77 and
    @BlackMoon1985 are one artist's accounts when the number is only whatever was free on each site. None when too
    little is left (`STEM_MIN`)."""
    key = name_key(handle_text(url))
    stem = key.rstrip("0123456789")
    return (stem, stem == key) if len(stem) >= STEM_MIN else None


def card_name(urls, display=""):
    """What a card is called: the artist's @name -- the account name of its first account on a site that has one (HANDLE_KINDS
    in that order), else `display`, the name the site shows. Where several accounts agree on a name but for the digits at its
    end (@Blackmoon, @blackmoon_77), the name without them: the one the artist is known by."""
    ranked = sorted(urls, key=lambda u: HANDLE_KINDS.index(sources.kind_of(u)) if sources.kind_of(u) in HANDLE_KINDS else 99)
    found = [h for h in (handle_text(u) for u in ranked) if h]
    if not found:
        return display
    stems = {name_key(h).rstrip("0123456789") for h in found}
    if len(found) > 1 and len(stems) == 1 and len(next(iter(stems))) >= STEM_MIN:
        plain = next((h for h in found if name_key(h) in stems), None)         # one of them is the plain name already
        cut = re.sub(r"[\d_.\-\s]+$", "", found[0])
        return plain or (cut if name_key(cut) in stems else found[0])
    return found[0]


def _loads(text):
    try:
        out = json.loads(text) if text else []
    except ValueError:
        return []
    return [u for u in out if isinstance(u, str)] if isinstance(out, list) else []


class _Twins:
    """The cards by name and by account name, the kinds of site each has a source on, and what the profiles name: who may
    take another account of the same artist. Read once for a look and kept up to date as it adds, not asked for every page.

    Evidence, strongest first: a profile that names the other account (`sources.links`: pixiv's declared twitter, a
    Mastodon field, Fanbox's links -- the artist's own word); the same account name (@mewnet on two sites); the same
    display name. Never two accounts of one site, whatever the evidence."""
    MIN = 3                                   # a shorter name says too little (and CJK names are short)

    def __init__(self):
        self.names, self.kinds, self.listed, self.attached = {}, {}, {}, 0
        self.owner, self.urls, self.declared, self.named_by, self.alias = {}, {}, {}, {}, {}
        self.stems = {}                           # stem -> [(card, whether the account is the plain stem)]
        with db.connect() as c:
            for r in c.execute("SELECT id, name, listed FROM artists ORDER BY id"):
                self.register(r["id"], r["name"], bool(r["listed"]))
            for r in c.execute("SELECT artist_id, url, links, alias FROM sources"):
                self.attach(r["artist_id"], sources.kind_of(r["url"]), r["url"], _loads(r["links"]), r["alias"])

    def register(self, artist_id, name, listed):
        self.listed[artist_id] = listed
        self.kinds.setdefault(artist_id, set())
        for key in {name_key(name), _base_key(name)}:
            if len(key) >= self.MIN:
                self.names.setdefault(key, []).append(artist_id)

    def url_keys(self, url):
        """The names an account is found by: the name the site shows, its account name and that without the digits."""
        alias = self.alias.get(url) or ""
        return {k for k in (name_key(alias), _base_key(alias), handle_key(url)) if len(k) >= self.MIN}

    def attach(self, artist_id, kind, url=None, links=(), alias=None):
        self.kinds.setdefault(artist_id, set()).add(kind)
        if not url:
            return
        url = url.lower()
        self.owner[url] = artist_id
        self.urls.setdefault(artist_id, set()).add(url)
        if alias:
            self.alias[url] = alias
        for key in self.url_keys(url):
            self.names.setdefault(key, []).append(artist_id)           # found as a name is
        stem = stem_of(url)
        if stem:
            self.stems.setdefault(stem[0], []).append((artist_id, stem[1]))
        for link in links:
            self.declared.setdefault(artist_id, set()).add(link)
            self.named_by.setdefault(link, set()).add(artist_id)

    def said(self, links, url, kinds, skip=()):
        """The cards that a profile says are the same artist -- the one named by `links` (an account's own), or naming
        `url` -- without a source of `kinds`."""
        ids = {self.owner[link] for link in links if link in self.owner} | self.named_by.get((url or "").lower(), set())
        return [i for i in sorted(ids) if i not in skip and not (self.kinds[i] & kinds)]

    def pick(self, ids):
        """The one card out of ids: a card the user made beats a listed one, and two of either make it unclear: None
        (an automatic join cannot be undone, so the lowest id is not a reason: three 'Mochi' are three artists)."""
        mine = [i for i in ids if not self.listed[i]]
        pool = mine or list(ids)
        return pool[0] if len(pool) == 1 else None

    def by_stem(self, url, name, kinds, skip=(), below=None):
        """The listed cards an account joins by its name without the digits -- the weakest evidence there is, so only
        where it is not likely two people: one of the two names is the plain one (@blackmoon and @blackmoon_77: the
        number is what was free on the other site) or the display names say the same too; never a card the user made
        (an automatic join cannot be undone); and only when exactly one card fits."""
        stem = stem_of(url or "")
        if not stem:
            return None
        said = {i for key in {name_key(name), _base_key(name)} if len(key) >= self.MIN for i in self.names.get(key, ())}
        found = {i for i, plain in self.stems.get(stem[0], ())
                 if i not in skip and self.listed.get(i) and (below is None or i < below) and not (self.kinds[i] & kinds)
                 and (plain != stem[1] or i in said)}
        return found.pop() if len(found) == 1 else None

    def find(self, name, kinds, url=None, links=()):
        """The one card that takes an account called name (at url, naming links) with sources of these kinds, or None.
        An unsupported site never conflicts."""
        kinds = kinds - {"unsupported"}
        said = self.said(links, url, kinds)
        if said:
            return self.pick(said)
        keys = {name_key(name), _base_key(name), handle_key(url or "")} - {""}
        ids = {i for key in keys for i in self.names.get(key, ())}
        strong = [i for i in sorted(ids) if not (self.kinds[i] & kinds)]
        return self.pick(strong) if strong else self.by_stem(url, name, kinds)

    def absorb(self, target, card):
        """The card went into target: its accounts, kinds and declared links are target's now."""
        self.kinds[target] |= self.kinds[card]
        self.listed[target] = self.listed[target] and self.listed[card]
        for url in self.urls.pop(card, ()):
            self.owner[url] = target
            self.urls.setdefault(target, set()).add(url)
            for key in self.url_keys(url):
                self.names.setdefault(key, []).append(target)
            stem = stem_of(url)
            if stem:
                self.stems.setdefault(stem[0], []).append((target, stem[1]))
        self.declared.setdefault(target, set()).update(self.declared.pop(card, ()))
        for named in self.named_by.values():
            if card in named:
                named.discard(card)
                named.add(target)


def _add(page, kind, public, twins=None, stats=None):
    """Cards for the accounts of a page not seen before; one that has a twin on another site joins its card
    instead. Returns (cards made, cards a follow joined to, page was all known).
    public: host -> whether it is a public one, kept for the whole look. twins: _Twins of the look.
    stats: a Counter that says where every account of the page went (_look logs it: "158 follows, 106 cards" must be explainable)."""
    stats = collections.Counter() if stats is None else stats
    mine, blocked = [], 0
    for f in page:
        raw = f.get("url") or ""
        site = sources.site_for(raw)
        # Only a profile of the list's own site: normalising another site's address (a pixiv work's)
        # is a request, and a hostile server could name any host.
        # (a Mastodon list names Misskey accounts too: Mastodon follows across the fediverse)
        # (a Mastodon or Misskey list names accounts of the other kind too: the fediverse follows across both)
        if site and (site.KIND == kind or {kind, site.KIND} == {"mastodon", "misskey"}):
            host = urllib.parse.urlsplit(raw).hostname or ""
            if host not in public:
                public[host] = net.public_https(raw)
            if public[host]:
                mine.append((sources.normalize(raw), f))
            else:
                blocked += 1                                # not 'known': the walk goes on, and _look says so
                stats["not public: " + host] += 1
        else:                                               # a Pixelfed, a Lemmy, a bridged account: nothing Sourcerer reads
            stats["other site: " + (urllib.parse.urlsplit(raw).hostname or raw[:40] or "no address")] += 1
    made, joined, known = [], [], len(page) - len(mine) - blocked
    with db.connect() as con:
        have = {r[0].lower() for r in con.execute("SELECT url FROM sources")}
        taken = {sync.safe_name(r[0]).lower() for r in con.execute("SELECT name FROM artists")}
        for url, f in mine:
            key = url.lower()
            headers = f.get("avatar_headers")
            links = [u for u in (f.get("links") or []) if isinstance(u, str)]
            mentions = [u for u in (f.get("mentions") or []) if isinstance(u, str)]
            if not con.execute("INSERT OR IGNORE INTO followed (url, avatar, headers) VALUES (?, ?, ?)",
                               (key, f.get("avatar") or "", json.dumps(headers) if headers else "")).rowcount:
                known += 1
                stats["known"] += 1
                if links:                                   # a card made before profiles' links were kept: it learns them here
                    con.execute("UPDATE sources SET links = ? WHERE lower(url) = ? AND links IS NULL", (json.dumps(links), key))
                if mentions:
                    con.execute("UPDATE sources SET mentions = ? WHERE lower(url) = ? AND mentions IS NULL", (json.dumps(mentions), key))
                continue
            if key in have:
                stats["has a card"] += 1
                continue                                    # a card of the user's has it already
            have.add(key)
            name, site_kind = _name(f, url), sources.kind_of(url)
            twin = twins.find(name, {site_kind}, url, links) if twins else None
            if twin and not con.execute("SELECT 1 FROM artists WHERE id = ?", (twin,)).fetchone():
                twin = None                                 # merged away by combine() since this look began: the account gets a card of its own
            picture = f.get("avatar") if isinstance(f.get("avatar"), str) and f["avatar"].startswith("https://") else None
            if twin:                                        # the same artist on another site: one card
                con.execute("INSERT INTO sources (artist_id, url, kind, links, mentions, alias) VALUES (?, ?, ?, ?, ?, ?)",
                            (twin, url, site_kind, json.dumps(links) if links else None, json.dumps(mentions) if mentions else None, name))
                if picture:
                    con.execute("UPDATE artists SET avatar_url = ?, avatar_headers = ? WHERE id = ? AND avatar_url IS NULL",
                                (picture, json.dumps(headers) if headers else None, twin))
                twins.attach(twin, site_kind, url, links, name)
                twins.attached += 1
                joined.append(twin)
                stats["joined an artist"] += 1
                continue
            artist_id = con.execute("INSERT INTO artists (name, listed, avatar_url, avatar_headers) VALUES (?, 1, ?, ?)",
                                    (_unique(card_name([url], name), url, taken), picture, json.dumps(headers) if headers and picture else None)).lastrowid
            con.execute("INSERT INTO sources (artist_id, url, kind, links, mentions, alias) VALUES (?, ?, ?, ?, ?, ?)",
                        (artist_id, url, site_kind, json.dumps(links) if links else None, json.dumps(mentions) if mentions else None, name))
            if twins:
                twins.register(artist_id, name, True)
                twins.attach(artist_id, site_kind, url, links, name)
            made.append(artist_id)
            stats["new card"] += 1
    if made or (twins and twins.attached):
        _touch()
    return made, joined, bool(page) and known == len(page)


# ---- the lists ------------------------------------------------------------------------

def _retry_soon(site, key):
    """A costly list that did not come whole is looked at again after RETRY_HOURS, not at the next ten to fourteen hours."""
    global _retry
    hours = getattr(site, "FOLLOWS_HOURS", 0)
    if hours:
        _retry = True
        db.set_setting("follows_at:" + key, str(time.time() - max(0, hours - RETRY_HOURS) * 3600))


def _prime(page, kind, public):
    """The hosts of a page resolved before the page is added: _add runs under _adding, and a slow resolver would hold every other
    login's cards up (net.public_https asks the DNS)."""
    for f in page:
        raw = f.get("url") or ""
        site = sources.site_for(raw)
        if site and (site.KIND == kind or {kind, site.KIND} == {"mastodon", "misskey"}):
            host = urllib.parse.urlsplit(raw).hostname or ""
            if host not in public:
                public[host] = net.public_https(raw)


def _look(key):
    """One login's lists. Returns how many cards they made."""
    global _retry
    db.set_setting("follows_at:" + key, str(time.time()))
    db.set_setting("follows_seen:" + key, "0")        # until a look has read accounts, the next start looks again (look())
    site, label, total, public, twins, seen = _site(key), accounts.label(key), 0, {}, _Twins(), 0
    fallback, early, stats = False, False, collections.Counter()
    asked = []                                         # cards this look made or joined: they get their first look (below)
    # A list read to its end by *this* login (a new login is another account, maybe) may stop early.
    stamp = accounts.saved(key) or "-"
    try:
        for name, pages, *note in site.following(key):
            if note and note[0]:                      # the site's own list did not come: what was taken instead, and why
                sync.event("warn", "%s: %s" % (label, note[0]))
                fallback = True
            done = "follows_read:%s:%s" % (key, name)
            for page in pages:
                seen += len(page)
                _prime(page, site.KIND, public)
                with _adding:                        # (the lists of several logins are read side by side, the cards made one look at a time)
                    made, joined, all_known = _add(page, site.KIND, public, twins, stats)
                total += len(made)
                asked += made + joined
                if all_known and db.get_setting(done, "") == stamp:
                    early = True
                    break                    # read to its end before: the rest is known
            else:
                if not fallback:                      # a list that was cut off is not "read to its end": its tail is read at the next look
                    db.set_setting(done, stamp)
    except Exception as e:
        why = net.reason(e)
        if not getattr(e, "final", False):            # (a list that is empty for good -- an account that follows nobody -- is not asked again within hours)
            _retry_soon(site, key)                    # a failed look of a costly list: tried again after RETRY_HOURS (start())
        log.info("%s: the list of followed accounts stopped: %s", key, why)
        sync.event("warn", "%s: the list of followed accounts stopped (%s); the next look carries on" % (label, why))
    else:
        if fallback:                                  # a part of the list is no list: the full one is tried again soon, not after a day
            _retry_soon(site, key)
        elif seen:
            db.set_setting("follows_seen:" + key, str(seen))
        if not seen and key not in _told_empty:         # an empty list used to be silent, and "my follows are missing" left no trace
            _told_empty.add(key)
            sync.event("info", "%s: the site's list of followed accounts is empty" % label)
    bad = sorted(h for h, ok in public.items() if not ok)
    if bad:                                           # these accounts were dropped without a trace before
        sync.event("warn", "%s: accounts on %s were left out: the address does not resolve to a public https site "
                           "(a VPN, a proxy or a DNS filter?)" % (label, ", ".join(bad[:3])))
    if seen:                                          # where every account went: "158 follows, 106 cards" is explained by this line
        kinds = ("new card", "joined an artist", "has a card", "known")
        left = sorted((k, n) for k, n in stats.items() if k not in kinds)
        sync.event("info", "%s: %d followed account%s read: %s%s" % (
            label, seen, "" if seen == 1 else "s",
            ", ".join("%d %s" % (stats[k], k) for k in kinds if stats[k]) or "none new",
            ("; left out: " + ", ".join("%s (%d)" % kn for kn in left[:12]) +
             (" ..." if len(left) > 12 else "")) if left else "") + ("; stopped at the first page of known accounts" if early else ""))

    if total or twins.attached:
        _touch(True)
        sync.event("info", "%s: %d followed account%s added to the list%s" % (
            label, total + twins.attached, "" if total + twins.attached == 1 else "s",
            " (%d joined an artist they are the same as)" % twins.attached if twins.attached else ""))
    if asked:
        # A card made from a login's follows is in nobody's sweep: Sync all and the automatic sync leave
        # cards only listed alone, so a card somebody follows stays empty until somebody notices it is
        # empty. Ask for the cards this look made, and the ones a follow joined to an existing card (its
        # new account needs a look too): the newest pages, no download -- a follow list can be a hundred
        # names a day, and the pictures come when they are asked for. A card with auto-download on does
        # download, as it always did. auto=True: Sourcerer asked, so the cards stay cards nobody has
        # touched (Manage Accounts does not change what a card is).
        queued = sync.enqueue(asked, auto=True)
        if queued:
            sync.event("info", "%s: %d card%s put into the queue for their first look" % (
                label, queued, "" if queued == 1 else "s"))
    return total


def combine():
    """Put the cards that are one artist together: every *listed* card (nobody has touched it) joins a card that is the
    same artist and has no source on the same site -- by what the profiles name (`_Twins`), else by the account name in
    the address, else by the display name. The older listed card keeps the name when both are listed, a card the user
    made always does; two of the user's cards that fit are left to them (the merge dialog suggests it). A card that is
    syncing is skipped until the next time. Returns how many cards went."""
    twins, gone, done = _Twins(), set(), 0
    with db.connect() as con:
        listed = [r[0] for r in con.execute("SELECT id FROM artists WHERE listed = 1 ORDER BY id")]
        names = {r[0]: r[1] for r in con.execute("SELECT id, name FROM artists")}
    for card in listed:
        if card in gone:
            continue
        kinds = twins.kinds[card] - {"unsupported"}
        # An older listed card takes this one; a younger one is left to its own turn, when this one is its twin.
        fits = lambda i: not (twins.kinds[i] & kinds) and (not twins.listed[i] or i < card)
        # What the profiles say: an account of this card names another card's, or the other way round.
        said = {twins.owner[link] for link in twins.declared.get(card, ()) if link in twins.owner}
        for url in twins.urls.get(card, ()):
            said |= twins.named_by.get(url, set())
        said = [i for i in sorted(said - {card} - gone) if fits(i)]
        if said:
            target = twins.pick(said)
        else:
            keys = {name_key(names[card]), _base_key(names[card])}.union(*(twins.url_keys(u) for u in twins.urls.get(card, ())))
            near = {i for key in keys if len(key) >= twins.MIN for i in twins.names.get(key, ())} - {card} - gone
            target = twins.pick([i for i in sorted(near) if fits(i)])
            if target is None and not near:        # nothing by name: the name without its digits, the weakest evidence (by_stem)
                target = next((t for t in (twins.by_stem(u, names[card], kinds, {card} | gone, below=card)
                                           for u in sorted(twins.urls.get(card, ()))) if t), None)
        if target is None:
            continue
        try:
            sync.merge(target, card, auto=True)
        except (sync.Busy, KeyError, ValueError) as e:
            log.info("cards %d and %d not combined: %s", target, card, e)
            continue
        gone.add(card)
        done += 1
        twins.absorb(target, card)
    if done:
        _touch(True)
        sync.event("info", "%d duplicate card%s combined: the same artist's accounts on different sites" % (done, "" if done == 1 else "s"))
    return done


class _Names(collections.Counter):
    """The folder names of the cards, counted: `_unique` asks `in` and `add`, and a card being renamed leaves its own out."""
    def __contains__(self, key):
        return self[key] > 0

    def add(self, key):
        self[key] += 1


def rename_listed():
    """Every *listed* card that has nothing downloaded is called by its @name (`card_name`): its name -- and the folder
    that follows from it -- is free to change, and it follows the accounts a card gains by combining. A card with files
    keeps its name (listed is only cleared by an edit, a sync, auto-download or a merge: a picture saved in Browse leaves
    it listed, and a new name would split the artist over two folders), as does one the user touched. Returns how many
    were renamed."""
    done = 0
    with db.connect() as con:
        cards = con.execute("SELECT id, name FROM artists WHERE listed = 1 AND NOT EXISTS "
                            "(SELECT 1 FROM files f WHERE f.artist_id = artists.id AND f.path IS NOT NULL) ORDER BY id").fetchall()
        if not cards:
            return 0
        urls = {}
        for r in con.execute("SELECT artist_id, url FROM sources ORDER BY id"):
            urls.setdefault(r[0], []).append(r[1])
        taken = _Names(sync.safe_name(r[0]).lower() for r in con.execute("SELECT name FROM artists"))
        for card in cards:
            mine = urls.get(card["id"])
            want = card_name(mine, card["name"]) if mine else card["name"]
            if want == card["name"]:
                continue
            own = sync.safe_name(card["name"]).lower()
            taken[own] -= 1
            name = _unique(want, mine[0], taken)             # (adds the name it takes; the old one is free now)
            if name == card["name"]:
                continue
            if con.execute("UPDATE artists SET name = ? WHERE id = ? AND listed = 1", (name, card["id"])).rowcount:
                done += 1
            else:                                             # touched since: it keeps its name
                taken[sync.safe_name(name).lower()] -= 1
                taken[own] += 1
    if done:
        _touch(True)
    return done


_told_skipped = set()        # logins whose list waits, said once per run: a silent skip left "my follows are missing" with no trace


def _say_skipped(only):
    """A login that cannot be read right now says why in the log, once (an expired login, a site that rests)."""
    for a in accounts.accounts():
        key = a["key"]
        if (only and key not in only) or not getattr(_site(key), "following", None) or not a["logged_in"] or key in _told_skipped:
            continue
        why = "its login ran out -- log in again in Manage Accounts" if a["state"] == "expired" else \
            "the site rests for now" if net.paused(sync._site_url(key)) else ""
        if why:
            _told_skipped.add(key)
            sync.event("warn", "%s: the list of followed accounts waits: %s" % (a["label"], why))


def look(only=None):
    """Every login's followed accounts (or those of the keys in only), each login in its own thread (X's list must not
    wait behind pixiv's, which takes minutes); then the cards that turn out to be one artist are combined."""
    global _retry
    if db.get_setting("import_follows") == "1":
        _say_skipped(only)
        todo = []
        for key in only or keys():
            if net.paused(sync._site_url(key)):
                _retry = True                         # a rest ends within hours: ask again then, not after ten to fourteen
                continue
            hours = getattr(_site(key), "FOLLOWS_HOURS", 0)      # a list that is costly to read is read less often
            # ... but only once it has given accounts: a look that found none (an older version's, a list that failed to
            # parse) must not hold the next one back for a day -- that was "X still shows nothing" after the fix came.
            gap = (hours * 3600 if int(db.get_setting("follows_seen:" + key, "0") or 0) else RETRY_HOURS * 3600) if hours else 0
            if gap and not only and time.time() - float(db.get_setting("follows_at:" + key, "0") or 0) < gap:
                continue
            todo.append(key)
        threads = [threading.Thread(target=_look_one, args=(key,), daemon=True, name="follows:" + key) for key in todo]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    with _lock, _adding:                                  # (never between two pages of a look that is still adding cards)
        combine()
        rename_listed()


def _look_one(key):
    with _reading.setdefault(key, threading.Lock()):
        try:
            _look(key)
        except Exception:
            log.exception("follows %s", key)


def look_async(only=None):
    threading.Thread(target=look, args=(only,), daemon=True, name="follows").start()


def _after_login(key, how):
    if how in ("new", "renewed") and getattr(_site(key), "following", None):
        look_async([key])


accounts.CHANGED.append(_after_login)


def start():
    """After the start's account check (sync.scheduler) -- an expired login is then known and
    skipped -- and every ten to fourteen hours."""
    def run():
        time.sleep(random.uniform(90, 150))
        global _retry
        while True:
            _retry = False
            try:
                look()
            except Exception:
                log.exception("follows")
            began, wait = time.time(), random.uniform(*HOURS) * 3600
            while time.time() - began < (RETRY_HOURS * 3600 if _retry else wait):     # (a look started by a login may ask for it meanwhile)
                time.sleep(60)
    threading.Thread(target=run, daemon=True, name="follows").start()
