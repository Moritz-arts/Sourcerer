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
| XenForo Media Gallery | **works** — media gallery, albums, threads (gallery-dl); login per forum; forums behind a Cloudflare challenge only with the login window's pass; forums that route only through `index.php?` (a guard) and forums in a folder log in, keep their login across redirects and list (base named to gallery-dl) |
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
- ~~2026-10-10 — Every new version also replaces Sourcerer.zip on the prerelease
  `beta`. — A clean download of the newest build without publishing a release
  by hand; Stable stays what was published deliberately.~~ Replaced 2026-10-17 (below).
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

- 2026-10-16 — **Sync is not download.** The user: downloading from galleries was
  still slow, Browse took long to load, cards showed no pictures before a sync,
  and "sync and download should be separated: download / auto-download downloads
  the artist, sync is for refreshing". So: *Sync* looks at the newest posts of
  every source and keeps them (snapshots); *Download* fetches what is missing;
  each card has an **Auto-download** switch (a sync of it downloads too, so does
  Automatic sync). Cards that exist when this arrives get it switched on once --
  nothing they did before stops. Browse opens from the snapshots (instant) and
  checks the sites meanwhile; the previews use them too and are allowed one first
  look at a login site. A login's interactive requests may go at 0.5-1 s instead of
  2-3 s (a person is waiting; sync keeps its pace). Squares / Full for the grid
  follows TrackImage's justified rows. A card has sync, download, open folder and
  delete; a double-click opens its Browse view (edit: Enter, right-click, or the
  pencil in Browse).

- 2026-10-16 — **Browse polish.** The user: add an artist from Browse (a plus at the
  bottom of the list); the site spinner hopped instead of circling; the large view must
  scale up until it meets the window; the list needs *Alphabetic | Latest activity* and a
  number that counts sources, images or shows auto-download; right-click on a name
  deletes; some tiles were more pixelated than others although the pictures have the
  same resolution (a wide Full tile stretched a small thumb); thumbnails and the large
  view still loaded slowly; site logos instead of names on the filter and the tiles.
  Causes found: a global `.spin` rule, `max-width` that never enlarges, and a TLS
  handshake per picture (a thread per request). See CLAUDE.md, Browse traps.

- 2026-10-16 — **Browse is the window; the Cards view is gone.** The user, from a
  screenshot review: only Browse, nothing else; tiles show *just* the site's logo (no
  grey pill); a downloaded picture is a green tick, in the viewer a green *Downloaded*;
  no circle round a site chip on hover; auto-download is a cloud in the list that is
  always there (green on, dark grey off) and no longer an entry of the number's choice;
  *Sync all* is **Refresh**, Browse's *Download all* is **Download selected source(s)**;
  Manage Accounts shows each site's logo; the large view has the site's logo top left,
  the artist's picture and name bottom left, and wide arrow areas; the artist's
  right-click menu turns auto-download on and off; shortcuts must work (they were bound
  to the cards -- `U`, `D`, `O`, `Enter`, `Del`, the size keys did nothing in Browse);
  and the sites must not be asked again on every switch of filter or artist.
  So: a gallery that is left stays aside (up to 6, 15 minutes) and shows again from
  memory; the site filter only hides (every site is asked once per gallery, hiding or
  showing one costs no request); a dropped connection on a gallery picture is retried
  once. The mockups' card grid is superseded by the user's decision; the card dialog,
  the activity bar and the toolbar stay as in them.

- 2026-10-16 — **A standalone Windows build** beside Sourcerer.zip, not instead of it:
  PyInstaller, tested by starting it before it is published. The bundle's folder is named
  `Sourcerer_files` so paths and Userdata mean what they do in the repository. Updates are
  **by hand** for now. -- The user asked for an .exe; the earlier decision for a system Python
  and a venv stands for everybody who has one, and the launcher download keeps the in-app
  updater, which an exe cannot use as it is.
- 2026-10-17 — **Downloads like Pikura's, for all three systems:** `Sourcerer-Setup.exe`
  (installer, per user) + `Sourcerer-Windows.zip`, `Sourcerer-macOS-<arch>.dmg`,
  `Sourcerer-x86_64.AppImage` + `Sourcerer-Linux.tar.gz`, built on a runner per system and put
  on every release and on `beta`. The first version's smoke test failed on GitHub's API
  rationing the runner and kept every file off `beta`; the user found no .exe anywhere. Now
  only a TLS failure fails that check. macOS and the AppImage keep Userdata in the user's data
  folder (read-only places); Linux: the AppImage and the launcher's venv open a Qt window
  (PyQt6 from pip; browser when Qt cannot start), the one-file tar.gz stays browser-only.
  Unsigned, un-notarised.

- 2026-10-17 — **Publishing on command.** The user, comparing with TrackImage and Pikura:
  Sourcerer should be automated on GitHub -- a branch merged into main on command, and
  when wanted released as the Stable version -- and its download buttons should work like
  Pikura's. So: `publish.yml` (Run workflow: `branch`, `release`; Claude starts it too),
  `version-bump.yml` made callable, and the README's download table links to
  `releases/latest` as Pikura's does, not to files that may not exist yet. TrackImage has no
  such workflow -- its release is still drafted by hand -- so this is new, not copied.

- 2026-10-17 — **GitHub's releases hold the Stable version only; Beta is the main branch.**
  The user: a "beta" entry among the releases is not wanted, one stable release is, and the
  Beta version is taken from `main`, not from releases (as TrackImage's *Latest* does). So the
  `beta` prerelease and every upload to it are gone; the updater's Beta channel reads the
  newest commit of `main` and installs GitHub's archive of it; the standalone apps follow
  releases only. The README's download table is compact, as Pikura's: one row per system,
  installer and portable, every link the latest release, the first-start notes folded away.

- 2026-10-17 — **An update leaves nothing stale behind, and the standalone Windows build has as few
  files as it can.** The user, after looking at an installed copy: too many files (~125 beside the
  program), nothing German, and an update must update everything and remove what is gone. So: the
  installer clears the program's folder (never Userdata) before copying, and the in-app update of an
  installed Windows copy downloads the new setup, checks its checksum and runs it silently; the
  C-runtime forwarders and setuptools are left out of the bundle; Windows 10+ only; the installer is
  English only. macOS, the AppImage and portable copies are replaced as a whole by hand (one app / one
  file / delete-all-but-Userdata). ~~A one-file build was refused (slower start, more scanner trouble,
  every gallery-dl run unpacks again).~~ Reversed by the next entry.

- 2026-10-17 — **One file, like Pikura.** The user showed Pikura's install folder (a handful of
  files) beside Sourcerer's ~125: so Windows and the Linux tar.gz are now a single executable
  (PyInstaller `--onefile`) with `Userdata/` beside it; the AppImage and the macOS app stay one item
  with the program unpacked inside. Replaces the same day's refusal of one-file builds -- the costs
  (a start that unpacks, scanners' distrust) are accepted for a download that is one file; gallery-dl
  runs share the parent's unpacked folder so they stay quick, and a restart unpacks its own. Old
  copies (a folder with `Sourcerer_files/Userdata`) keep working and the installer moves the data out.

- 2026-10-18 — **The accounts a login follows are the list.** The user: logging in only opened
  the door, and only artists made by hand got through; the followed accounts should be in the list
  at once, with no download, and accounts that belong to one artist must be mergeable. So: after a
  login (and every ~12 h, and when the Settings switch is turned on) Bluesky, Mastodon and pixiv
  list their follows and every account becomes a card once -- *listed* (`artists.listed`): in
  no sweep (Sync all, automatic sync, All artists) until the user edits, syncs or merges
  it or turns auto-download on, because hundreds of cards read in the background would be hundreds
  of requests nobody asked for. What was added is remembered (`followed`), so a deleted card does
  not return. *Merge into...* (menu, `M`) moves a card's sources and files to another. X and Patreon
  are not in yet: X's follows need gallery-dl and the account's handle (and X locks accounts),
  Patreon's are memberships.
- 2026-10-20 — **No warning boxes, X and Patreon follows from the feeds, Browse's groups fold.** The user:
  the Log out / Delete / Quit / repair questions (`confirm()`) are unwanted -- *no* such box anywhere
  (Reset keeps its typed word: it wipes everything). The head's site chips overlapped (the `.logo` class of
  the brand mark made them 24 px wide). The artist list ordered by source folds and opens under each site's head.
  X's and Patreon's follows were still missing: X falls back to the Following timeline (`https://x.com/home`) when
  its full list does not come, Patreon reads memberships and the feed (`https://www.patreon.com/feed`); both
  say in the activity log what they took and why. Written from the sites' own requests, **not yet seen against a
  real X / Patreon login** -- the log line after the next look says what happened.
- 2026-10-20 — **All artists is all artists, with a time window; sites are named; the logs are explained.** The user (v0.36): Patreon's
  creators were missing in All artists, which left the followed (listed) cards out -- all cards are in it now, and to spare the sites it
  reaches back one week first (Settings: 2 weeks / month / 3 months / everything), with *Load older posts* at the end of the grid. A
  XenForo login window opened `/login/`, showed the guard's 403 for seconds and only then `index.php?login/`; it opens the second
  route directly now. "Mastodon" / "XenForo" said nothing about which site: the lists, chips and tiles use the server's, forum's or
  booru's own name and pull its icon (memory only). The logs: a viewer (Activity > Log files), a README in the folder, the console log
  holds only warnings and crashes, every start opens a block.

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
- [x] Sync and download separated: sync only looks (and counts what is
      waiting), download fetches; a per-card Auto-download switch decides whether
      a sync downloads too; cards have four buttons and open Browse on a double-click
- [x] Browse polish: Add artist, order and counter of the list, right-click menu, site
      logos, a circling spinner, the large view fills the window, sharper tiles, pictures
      through one pooled session and prefetched in the viewer
- [x] Browse is the only view (no Cards view): logo-only tiles, green tick / *Downloaded*,
      always-visible auto-download cloud and menu entry, Refresh, site logos in Manage Accounts
      and the viewer, working shortcuts, galleries kept aside so a switch asks no site
- [x] Browse opens from snapshots at once and checks the sites meanwhile (spinner,
      green chips, "N new posts"); Squares / Full picture layout; previews for cards
      with login sources without a sync first

- [x] Follows import: Bluesky, Mastodon, Misskey, pixiv, Fanbox, Fantia, X and Patreon follows become listed cards after a login;
      Merge into... for accounts the sites did not show to be one artist
- [x] Refresh one artist at a time, the opened artist first; only auto-download cards in sweeps; token logins
      (Bluesky, Mastodon, Misskey, boorus) no longer spaced like cookie logins; a cookie-login gap setting
- [x] Cards are worked on up to three at once when they share no cookie-login / gallery-dl site; speed settings
      worked out for the sites' limits (8 downloads, 4 per site, 0.25 s) and the old ones dropped once
- [x] Sourcerer keeps no pictures: no Avatars, no Previews (the table and the folders go at the start); a profile
      picture is an address, fetched into memory by /api/avatar
- [x] Follows of Misskey, Fanbox, Fantia and X become listed cards (X and Patreon were open; Patreon still is)
- [x] Pixiv's ugoira plays in the viewer (an animated WebP made in memory from pixiv's ZIP)
- [x] The window maximizes inside the work area (the taskbar stays), a download shows a green ring on its tile, the file's
      name shows on hover and in the viewer, the order list has four entries, the dot of a site's mark no longer cuts it
- [x] Refresh all looks at every artist down the list, scanning the ones that do not download (their newest page, "N new
      posts online"); the list is bigger; Quick is the standard grid quality; the gap between artists on a cookie login is
      careful 15-60 s, normal 10-30 s, fast 3-15 s; a sweep's scans stop at half of a login site's day (the rest is for
      downloads and Browse), and Cancel drops the queue
- [x] A picture in the library wears the download button, green, in its corner -- however it got there -- and loses it
      when the file is deleted
- [x] An entry of the activity log that names a failed file jumps to its picture in the artist's gallery (or its post)
- [x] The same artist is found by what the profiles name (declared twitter, Mastodon fields, Fanbox links), then by the
      account name in the address (@Mewnet), then by the display name -- in the automatic combining and the merge dialog
- [x] Cards are called by the artist's @name (X, Bluesky, Mastodon, Misskey, Patreon, Fanbox, forum), the digits at its end
      dropped where accounts agree (@Blackmoon / @blackmoon_77); the names the sites show stay as aliases and still
      find the card (combining, merge suggestions, the list's search); X's follow list says why when it fails
- [x] Misskey login (MiAuth) per server; Fanbox and Fantia as sources with a cookie login
- [x] Grid pictures in the largest rendition below the original (setting: Sharp / Quick); favorites
      (right-click, key F, star, order *Favorites*)
- [x] Misskey (misskey.io and forks) as a source: notes with files, no login; a Mastodon list's
      Misskey accounts are cards too; unknown Misskey servers are learned
- [x] Accounts of one name on different sites are combined on one card by themselves (as a login's
      follows come in, and for the cards already apart), never two accounts of one site
- [x] Settings: parallel downloads up to 64 and connections per site up to 32 (sites with their own lower
      limit keep it); Security pane with a master password (asked at every start, enforced by the server)
      and a reset to a fresh install; TrackImage's card in the settings rail
- [x] Browse: download one picture (arrow on the tile), several (select mode, Ctrl/Shift-click) or the whole artist; GIFs
      play; right-click copy in the grid too; more orders (Source, Source (logo), Image count, Downloads, Downloads %) with
      the matching numbers, "All artists" totals, images = total not downloaded; latest activity by the newest post;
      every start looks for new posts; no New card button; the window's title bar is the page's own on Windows
- [x] Viewer: bar on top, click on the dark closes it, double-click / wheel zoom, drag to move; Settings >
      Appearance: switch for the site mark on the pictures
- [x] Merge dialog: likely twins (same name but for emoji / marks / case, shared account name) listed at
      the top, several cards ticked and merged with one button, no extra confirmation; Browse can be
      ordered by source (logo and line per site)

## Next

- [ ] Follows of Patreon (memberships: the endpoint of the page "Memberships" is not documented and needs a real
      login to read; nothing is guessed until then), and a home
      timeline ("Following") in Browse that shows the newest posts of everybody a login follows
      with one request per page instead of one source per account.
- [ ] Standalone builds: an in-program update for macOS, the AppImage and the portable copies
      (an installed Windows copy has it), gallery-dl between releases (its wheel next to the
      program); look at the first real runs on all three systems; an app window on Linux (Qt?);
      sign / notarise if the warnings scare people off

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
- [ ] Browse: "All artists" reads a first page per source live when no snapshot
      exists yet; a background timeline that refreshes snapshots of cards
      nobody has opened would make even the first opening instant.
- [ ] Browse: select several pictures and download them together.
