# Sourcerer — roadmap

The working memory of the project: where it is going, what is decided, what is
next. Update it in the same commit as the work that changes it — tick a box,
add a decision, move an item. Anyone, with or without Claude, should be able to
pick the project up from this file and `CLAUDE.md` alone.

## Goal

A portable app for Windows, Linux and macOS that keeps per-artist media
collections in sync across sites and drops every new file, de-duplicated across
sources, into a TrackImage library.

## Sources

| Site | Status |
|---|---|
| XenForo Media Gallery | **works** — media gallery, albums, threads (gallery-dl); login per forum; forums behind a Cloudflare challenge only with the login window's pass |
| Mastodon (and the fediverse) | **works** — public posts, originals; login per server (OAuth) for members-only servers and followers-only posts |
| Patreon | **works** — own code on Patreon's JSON; originals (`download_url`), uploader's names; patron posts with a login |
| Bluesky | **works** — public posts, original blobs incl. video; login with an app password |
| X | **works** with a login — listed by gallery-dl, originals (`name=orig`) |
| Pixiv | **works** — own code on pixiv's AJAX JSON; R-18 with a login; ugoira as animated WebP |
| Boorus | **works** — Danbooru (+ Safebooru, AIBooru), e621/e926, Gelbooru, Rule 34, Safebooru.org, Xbooru, TBIB, Hypnohub, yande.re, Konachan, Sakugabooru: an artist's tag search; API keys where a site wants one |
| DeviantArt | not started |

## Decisions

Record each as: date — decision — why. Never delete one; strike it through and
add the one that replaced it.

- 2026-10-09 — Same workshop as TrackImage: version raised and changelog
  written by a workflow on every push to `main`, workshop files kept out of
  the archive. — One way of working across both projects.
- 2026-10-09 — The version lives in `Sourcerer_files/VERSION`, a plain file,
  not in code. — No code exists yet, and a plain file is the easiest thing for
  both the program and the updater to read.
- 2026-10-09 — Windows, Linux and macOS, each with a launcher in the root
  (`start-windows.bat`, `start-linux.sh`, `start-macos.command`). — Same
  reach as TrackImage.
- 2026-10-09 — The system Python (3.10+) and a `venv` inside `Sourcerer_files/`,
  as in TrackImage, instead of a bundled runtime; packages come from one
  `requirements.txt`. — One setup path for all three systems; the root stays
  clean because all machine state lives in `Sourcerer_files/`.
- 2026-10-10 — The launchers only find a Python 3.10+; `Sourcerer_files/launch.py`
  does everything after that (environment, packages, start). — One
  implementation instead of three shell languages, and testable on any system.
- 2026-10-10 — One venv per system (`venv/windows|linux|macos`), checked by
  running it; pip's cache inside `venv/`. — The folder is portable; a venv
  built by one system cannot run on another, and a broken one must heal itself.
- 2026-10-10 — The notes for Claude live in `.claude/CLAUDE.md`, not in the
  root. — The root holds only what a user needs to start Sourcerer.
- 2026-10-10 — Every published release gets `Sourcerer.zip`, with the
  launchers at its top, built by a workflow. — GitHub's own archive wraps
  everything in `Sourcerer-<ref>/`, so unpacking it gave two folder levels;
  Sourcerer.zip unpacks to exactly one, `Sourcerer/`.
- 2026-10-10 — The program is built like TrackImage: Flask on 127.0.0.1, a
  pywebview window (the browser when that cannot open), vanilla JS, SQLite in
  `Userdata/`. — Same stack, same habits, one person maintaining both.
- ~~2026-10-10 — Downloads go to `<library>/<artist>/<date>_<site>_<id>.<ext>`;
  a file is new when its remote key was never seen for the artist, and kept
  unless the same bytes are already there. — Sorted by date in any file
  manager; deleted files are not brought back; near-duplicates are left to
  TrackImage, which already finds them.~~ Replaced the same day.
- 2026-10-10 — Files keep the name they have on the site (Bluesky has none:
  the blob's id stands in); Settings can put the date in front. A file is new
  when its remote key was never seen for the artist. — The user asked for the
  original names; the date stays one click away.
- 2026-10-10 — The window follows the original design mockups (kept in
  `.claude/design/`): card grid with avatar, folder, four thumbnails, badges
  and progress; card dialog with source list, master source, folder layout and
  duplicate choice; activity bar with queue. — The user's design, agreed
  before any code.
- 2026-10-10 — Everything is English, the interface included. — The user's
  call; replaces the German interface of the mockups.
- 2026-10-10 — A card may have its own folder; empty means
  `<library>/<name>`. Renaming a card or choosing another folder moves the
  folder along when a rename can (same drive). — One artist never ends up in
  two folders; copying a whole collection inside a click is not on.
- 2026-10-10 — Updates and repair inside the program, like TrackImage:
  Sourcerer.zip of the chosen channel is checked and unpacked into
  `Userdata/_update/`, then a helper in the system temp folder, run by the
  system's Python, swaps `Sourcerer_files/`, carries `Userdata/` and `venv/`
  across, restores the old version on any failure and restarts. Repair
  reinstalls the installed version from its tag. — Same rules as TrackImage's
  updater, one implementation in Python for all three systems.
- 2026-10-10 — Sites are treated gently: official public APIs, an honest
  User-Agent, at most 2 requests per site at once with a pause between them,
  Retry-After honoured, automatic syncs jittered. — Speed is not worth a
  block; parallel downloads across sites and kept-alive connections make it
  fast enough.
- 2026-10-10 — The same picture from two sources is recognised by a
  difference hash (Pillow), and each artist chooses: keep all, best quality, or
  master source. Folder layout per artist: all together or per source. — What
  the card dialog mockup asks for; byte comparison alone misses every
  recompressed copy.
- ~~2026-10-10 — HTTP with the standard library, no requests. — Two calls do not
  justify a dependency on three systems.~~ Replaced the same day.
- 2026-10-10 — HTTP with `requests`: one session per thread, connections kept
  alive. — Parallel downloads and reused connections are what made syncing
  fast; the standard library opened a new TLS connection per file.
- 2026-10-10 — Every new version also replaces Sourcerer.zip on the prerelease
  `beta`. — A clean download of the newest build without publishing a release
  by hand; Stable stays what was published deliberately.
- 2026-10-11 — X and XenForo are listed by gallery-dl, run as a separate
  process; Sourcerer downloads the files itself. — X's web API changes
  almost weekly and gallery-dl follows it; a copy of our own would stay
  broken until the next release. A separate process keeps gallery-dl's
  GPL-2.0 apart from Sourcerer, which has no licence yet, and lets a pip
  upgrade (weekly, or Settings › Updates) fix X between Sourcerer releases.
- 2026-10-11 — Pixiv and Patreon in Sourcerer's own code, on the JSON their
  own pages read. — gallery-dl needs an OAuth refresh token for pixiv and
  poses as the pixiv/Patreon mobile apps (Patreon blocked outdated app
  versions in March 2026, breaking it); the JSON is simpler and honest.
- 2026-10-11 — User-Agent `Mozilla/5.0 (compatible; Sourcerer/<v>; +repo)`.
  — Still names Sourcerer, in the form crawlers use; pixiv's Cloudflare
  challenged every logged-in request whose UA did not start with Mozilla/5.0.
- 2026-10-11 — A file already there is taken over, not downloaded again:
  from the archive of deleted cards (by remote key), else by its own name in
  the card's folder. — Deleting and remaking a card downloaded everything a
  second time, as `name_2.jpg`.
- 2026-10-11 — Card pictures are made in memory from the downloads; no
  thumbnail files. Avatars are `Avatars/<artist>.jpg`. — The user wants no
  picture stored twice; SQLite hands out a deleted row's id again, so
  pictures keyed by id could show the wrong artist.
- 2026-10-11 — Logins are checked after every sync that uses them, at every
  start and every 6 hours; one that ran out shows as a warning until it is
  renewed.
- 2026-10-11 — Connections are TLS 1.3 only, on Python's own defaults, with
  TLS 1.2 kept for hosts that lack 1.3. — baraag.net (Mastodon) and
  VerticalScope's forums refused urllib3's handshake whatever the headers;
  this one passes, and Sourcerer still says who it is.
- ~~2026-10-11 — Every site has a login in Settings › Accounts, each the way
  the site offers: its login page in the window (cookies; Mastodon: OAuth
  with a read-only token), a Bluesky app password, a booru's API key. The
  card dialog says under a link when its site wants a login that is missing.~~
  Moved to Manage Accounts on 2026-10-15 (below); the ways to log in stay.
- 2026-10-11 — Boorus in Sourcerer's own code on their JSON APIs, not
  gallery-dl: three engines, small and stable; a source is a tag search.
- 2026-10-12 — Protecting logged-in accounts comes before speed: a login's
  requests go one at a time, at least 2 s apart from the end of the last,
  with random gaps and reading breaks; a daily budget per site; a site that
  objects (429, bot check, refused login, X's limits) rests for hours, saved
  across restarts; automatic syncs at random times, oldest card first, hours
  apart per login site. — The user's priority: no account banned for looking
  like a bot. Regular timing and bursts are what bot detection looks for.
- 2026-10-12 — A gallery per card: the sources' listings merged newest
  first, straight from the sites, nothing written to disk. The page loads
  plain CDNs itself (no referrer); what needs a Referer or a login comes
  through Sourcerer, only for items a listing handed out, cached in memory
  (160 MB) and dropped on close. Download saves through the sync's own
  path. — The user wants to browse an artist without downloading
  everything. Pikura (GPL-3.0, ideas only, no code) does the same with
  pixiv's small previews and a Referer; Sourcerer keeps no disk cache.

- 2026-10-15 — Logins moved out of Settings into **Manage Accounts**, a
  button beside *Sync all* that turns red when a login ran out: one box per
  login with a dot (green works, red ran out, hollow not logged in), the
  fields in the box, no "add another" lines (Mastodon, XenForo and Booru show
  one blank box until a login of their kind exists). The card dialog lists
  only the sites with a saved login, no longer offers "Add another link", and
  keeps the rows of links already on the card. — The user: a link only works
  once its account is set up, and the accounts page should be nothing but the
  boxes.

- 2026-10-15 — **Manage your accounts** lists only logins that exist; a site
  is added with *Add account* at the end, by choosing its type (and, for a
  booru, the booru -- no default, so no Gelbooru row appears on its own).
  **The gallery** asks its sources at the same time and a page leaves after a
  few seconds without the slow ones; the next page is fetched one page ahead;
  small pictures from a CDN load four at a time; a download goes ahead of
  the queue. **Cards** show the 4 newest posts of their sources, found on the
  sites and kept as small copies in `Userdata/Previews` (a cache), so a new
  card is not empty until its first sync. — The user: duplicate boxes and a
  pre-selected Gelbooru confused; the gallery and its download were slow;
  cards should show the newest pictures without downloading them first.

- 2026-10-15 — **Browse**, a second view beside the cards (*Cards | Browse*):
  the artists the user follows on the left, their posts on the right, from
  every source at once, with a filter by site and a download of one picture
  or of everything the switched-on sites have. "All artists" is one timeline
  over every card. It is the gallery moved out of its dialog into the window,
  not a second implementation. — The user wants "Instagram, but from all
  platforms": follow favourite artists across sites in one app, and download
  from the sources they choose, or all. Pikura (GPL-3.0, pixiv only) was the
  picture of the layout; no code taken. Next: a cached timeline so "All
  artists" opens without asking every site (see below).

## Done

- [x] Repository workshop: CLAUDE.md, docs, version workflow
- [x] Launchers for Windows, Linux and macOS; `app.py` placeholder
- [x] Audit: launchers, version workflow and docs checked and corrected
- [x] Program skeleton: window, artist cards (name, notes, source links),
      settings (library folder), background sync with status and log
- [x] First sources: Mastodon and Bluesky
- [x] Design from the mockups: card grid, search and sort, card dialog,
      sync queue with progress and cancel, activity bar with log
- [x] Same picture across sources: keep all / best quality / master source;
      folder layout together / per source
- [x] English interface, logo and favicon; "+" tile; card size slider
      (Ctrl + wheel); keyboard and mouse like TrackImage; right-click menu
- [x] Card dialog: links normalised (`/media`, posts → profile), live dot per
      link, name and profile picture from the links, own folder per card,
      "Create" / "Create & sync"
- [x] Original file names; parallel downloads; per-site limits
- [x] Settings like TrackImage: library, file names, automatic sync,
      parallel downloads, network limits, theme, card size, shortcuts,
      updates (Stable / Beta), repair, about
- [x] Updater and repair (reinstall, rebuild environment, redraw thumbnails,
      re-check links, restart)
- [x] Activity bar with progress, speed and queue; log with icons and a
      "Problems" filter
- [x] The console closes once Sourcerer is up; one Sourcerer at a time
- [x] Card dialog with a field per site; gallery button on the card
- [x] Logins in Sourcerer's own window (cookies only, never passwords),
      cookies.txt import; a warning when a login runs out
- [x] Pixiv, Patreon, X, XenForo
- [x] Files already there are taken over, not downloaded again (archive of
      deleted cards, original names in the folder)
- [x] Card pictures made in memory from the downloads; avatars named after
      the artist; dots green / yellow / red; links on the card open the site
- [x] TLS 1.3 handshake: Mastodon servers and forums with a bot check work
- [x] Logins for every site (Bluesky, Mastodon, boorus added), checked at
      every start; the card dialog warns about a missing login
- [x] Boorus: Danbooru, e621, Gelbooru, Rule 34, yande.re, Konachan and more
- [x] Manage your accounts: one row per login that exists, one under the other,
      with a green / orange (the site rests) / red (ran out) dot, "Check all",
      a red badge on the toolbar button; *Add account* at the end chooses the type
      (and a booru) -- nothing pre-selected; the card dialog lists only logged-in sites
- [x] Manage Accounts: a *Login files* button opens the folder the logins are kept in
      (transparency; copy it to back the logins up, put it back to restore them)
- [x] Account safety: a login's slow lane with random gaps and breaks,
      daily budgets, site pauses, randomised automatic syncs and login
      checks, X's limits and locks respected, one gallery-dl per site
- [x] Gallery: all sources of a card in one stream, large view, download
- [x] Gallery faster: sources asked at the same time, the next page fetched ahead,
      small pictures through their own lane, a download ahead of the queue
- [x] Cards show the 4 newest posts of their sources without any download
- [x] Browse: artists left, their posts from every source right, "All artists"
      as one timeline, a site filter, download one picture or everything from
      the sites that are on

## Next

- [ ] Forums behind a Cloudflare challenge without a login: fetch their
      pages through the login window's browser engine. (VerticalScope's
      `xf_is_suspected_bot` 409 is solved by the TLS 1.3 handshake.)
- [ ] Mastodon: an artist on a server the user has no account on, read
      through the user's own server (only what it has seen).
- [ ] A licence for Sourcerer. Until there is one, gallery-dl (GPL-2.0)
      stays a separate process.
- [ ] DeviantArt (gallery-dl lists it without a login, but not always the original)
- [ ] Updater, first real run on Windows and macOS (simulated on Linux:
      swap, rollback, restart)
- [ ] Where Sourcerer hands files to TrackImage, and how duplicates are matched
- [ ] X: resume a long first sync where it stopped instead of listing the
      newest pages again (gallery-dl's cursor).
- [ ] Quiet hours: no automatic sync of a logged-in site at night.
- [ ] Gallery: a filter by date.
- [ ] Browse: "All artists" reads every source's first page live. A cached
      timeline (the first pages kept by the background worker that already
      fetches the cards' previews) would open at once and ask the login sites
      less; downloads from it need the sites' `Media.fetch` rebuilt.
- [ ] Browse: select several pictures and download them together.
