# Working on Sourcerer

A portable app for Windows, Linux and macOS that keeps per-artist media
collections in sync across sites and drops every new file, de-duplicated across
sources, into a [TrackImage](https://github.com/Moritz-arts/TrackImage) library. Sibling
project of TrackImage, built the same way: the repository *is* the program —
what people download and unpack is these folders, unchanged.

**Status: early development.** What exists: the three launchers with
`launch.py` behind them; the program — a window with artist cards, a card
dialog (sources with a live dot each, own folder, master source, folder
layout, what to do with the same picture from two sources), a queued
background sync that downloads from Bluesky, Mastodon, Pixiv, Patreon, X,
XenForo forums and boorus, a gallery per card (all its sources, straight from
the sites), a login for every site (Manage Accounts, checked at each start),
settings like TrackImage's, and an
updater with Stable/Beta and repair; and the workshop —
these notes, the docs and the automation that versions every push. `Sourcerer_files/sourcerer/__init__.py`
lists the program's layers.

**The design is fixed by two mockups in `.claude/design/`** — the main window
and the artist card dialog. The page in `Sourcerer_files/static/` follows them:
their colours, sizes and layout. Change the look there only with the user, and
keep the mockups as the reference. **Everything is English** — the interface
too (the user's decision; the mockups' German wording is superseded), as are
code, comments and file names. The logo is `static/logo.svg`, also the
favicon.

## Where the knowledge lives

Everything somebody needs to carry on — with or without Claude — is in the
repository, never only in a chat:

| File | What it holds | Who keeps it current |
|---|---|---|
| `.claude/CLAUDE.md` (this file) | rules, traps, house style, checks | whoever learns something |
| `Sourcerer_files/docs/ROADMAP.md` | goal, sources, what is done and next | whoever finishes or decides something |
| `Sourcerer_files/docs/FOLDER_MAP.md` | the layout, file by file | whoever moves or adds a file |
| `Sourcerer_files/docs/CHANGELOG.md` | one line per change, per version | **the workflow — never by hand** |
| commit bodies | the reasoning behind each change | every commit |

**Keep them honest in the same commit as the change.** A trap that cost time
goes under *Traps* below; a new folder goes into the folder map; a finished
milestone or a decision goes into the roadmap. If it is only in a chat, it is
lost.

## Layout

`Sourcerer_files/docs/FOLDER_MAP.md` describes it in full. Read it before
moving anything.

The root stays short on purpose, so that starting Sourcerer means picking one
of three obvious files: README.md, the three launchers (`start-windows.bat`,
`start-linux.sh`, `start-macos.command`) and `Sourcerer_files/`. Everything
else lives in `Sourcerer_files/`, `docs/` and all machine state (`venv/`,
`Userdata/`) included; these notes live in `.claude/`, where Claude Code reads
them too. Do not add another file beside the launchers.

**What people download is not what the repository holds.** `.gitattributes`
marks the workshop files `export-ignore`, so `.github/`, `.claude/` and the
ignore lists are absent from the source archive GitHub builds. A new file that
belongs to the workshop rather than to the program goes in that list too. It
changes nothing for a clone, and Actions is unaffected: it checks the
repository out rather than unpacking an archive.

## Versioning — do not do this by hand

**Never edit a version number.** A workflow (`.github/workflows/version-bump.yml`)
raises it on every push to `main` and rewrites it everywhere it is written:

```
Sourcerer_files/VERSION     0.1            ← the one that counts
README.md                   # Sourcerer v0.1
```

The program reads its version from `Sourcerer_files/VERSION` and from nowhere
else — `launch.py` prints the banner from it, the launchers carry no number.
Do not spell the number out in code; a new place that must print it goes into
`PLACES` in `.github/bump_version.py`.

If a change genuinely must not raise the version, put `[skip version]` in the
**pull request's title** (merge commit and squash both carry it into the
message the workflow reads) or, for a direct push, in its last commit. In a
branch commit of a pull request it does nothing.

**Never write `[skip ci]` in a commit message, not even to talk about it.**
GitHub reads that marker anywhere in the message and skips the whole run, so a
commit *describing* the marker silently skips its own version bump (this cost
TrackImage a version once). In a commit message call it "the skip marker".
Inside a file like this one it is harmless; only commit messages are scanned.

**Never write the changelog by hand either.** The same workflow prepends an
entry from the commits since the previous tag — one line per commit, taken from
the subject. So **the commit subject is the changelog line**: write it as a
statement about what changed, in English, readable on its own.

```
good: Mastodon: new posts of a followed artist are fetched with their media
bad:  fix stuff / wip / address review
```

The body is where the reasoning goes — as much as it deserves. It does not
reach the changelog, and that is the point: the list stays short, the reasoning
stays with the diff.

## How a change reaches people

1. Work on the branch you were told to use, push it, open a pull request.
2. The user merges it into `main`.
3. The workflow raises the version, writes the changelog line, tags the commit
   (`v0.1`), and pushes commit and tag together. It does **not** publish a
   release. Two merges close together become one version listing both; when
   `main` moves while it runs, it starts over on top of the new state.
4. When the user judges a version ready, they draft a release from its tag by
   hand and paste that version's section out of
   `Sourcerer_files/docs/CHANGELOG.md`. Publishing it starts
   `.github/workflows/release-zip.yml`, which attaches **Sourcerer.zip**
   (`releases/latest/download/Sourcerer.zip`, the Stable download).
   Independently, every new version replaces Sourcerer.zip on the prerelease
   `beta` (`releases/download/beta/Sourcerer.zip`, the Beta download); its tag
   `beta` is moved by the workflow and by nothing else.

Do not create releases or tags yourself, and do not push to `main`.

## Traps

### Sourcerer's own

- **`Sourcerer_files/Userdata/` holds logins, tokens and cookies.** It is
  git-ignored and must stay that way. Never commit it, never write its
  contents to a log, never put a credential into a commit message, an issue or
  a test fixture.

### Inherited from TrackImage — they apply to the updater (`updater.py`)

- **A tag must sit on a commit that contains the version it names.** The
  workflow tags its own bump commit for this reason; never tag by hand.
- **An update replaces, it does not merge.** `Sourcerer_files/` is swapped
  whole. A file an older version shipped and this one does not survives on
  every machine that updates unless the updater deletes it by name.
- **A cleanup added to the update helper takes effect one version late.** The
  script that performs a swap comes from the version being replaced. Stale
  names must also be removed at start by the version that knows them.
- **User state belongs to the machine, not the program.** `Userdata/` and
  `venv/` sit inside `Sourcerer_files/`, which an update replaces whole, so the
  updater must move both across by hand. Forgetting one costs the user their
  logins or minutes of pip on every update.
- **The helper must not live in the folder it deletes.** A shell reads a
  script as it goes; delete the folder it is read from and execution simply
  stops. Write it to the system temp folder and let it delete itself last.
- **A backup belongs to the user.** Backups go to
  `Sourcerer_files/Userdata/Backup/`, never beside the launchers (TrackImage's
  ended up there after root-level ones proved to be clutter). Move old ones,
  never delete them as a "tidy-up"; keep a fixed number of recent ones.
- **A branch URL is cached, a commit URL cannot be.**
  `raw.githubusercontent.com` serves `…/main/…` with `max-age=300`. Ask the API
  for the head commit first, then read files *at that commit*.
- **The update helper runs unseen.** It logs every step to a file the app reads
  into its own console on the next start. On Windows, `timeout` and `pause` are
  ruled out (no console to read from); `ping -n` is the sleep, and every exit
  path restarts the app — including the failed ones.
- **`exit /b` does not close a console window; `exit` does.** And nothing the
  helper starts may wait for a keypress.
- **The installation folder keeps its name.** Renaming it per version breaks
  every shortcut somebody made to it.
- **GitHub's own archive wraps everything in `Sourcerer-<ref>/`.** "Download
  ZIP" and "Source code (zip)" both do, and it cannot be switched off:
  unpacked into a folder, that gave `Sourcerer/Sourcerer-main/`. So people get
  Sourcerer.zip instead, built by `git archive` with no prefix, which has the
  launchers at its top — from the latest release (Stable) or from the `beta`
  prerelease (Beta). The updater should use these two files too, not GitHub's
  archives.
- **Everything here is written in English — file and folder names included.**

### Launchers

- **The launchers only find Python; `launch.py` does the rest.** Each launcher
  looks for a Python 3.10+ in its system's way and hands over to
  `Sourcerer_files/launch.py`, which builds the environment, installs the
  packages and starts `app.py` — once, in Python, testable on any system.
  Anything more goes into `launch.py`, not into three shell languages that
  drift apart. Packages live in `Sourcerer_files/requirements.txt`.
- **The console is for the setup, not for the running program** (TrackImage's
  way). `launch.py` starts `app.py` detached -- `pythonw.exe` on Windows, a
  new session elsewhere -- and returns once `Userdata/running.json` names a
  port that answers `/api/ping`; then the console closes. A start that fails
  shows the tail of `Userdata/Logs/console.log` (the program's stdout and
  stderr) and keeps the console open. `--console` keeps the program attached,
  for debugging.
- **One Sourcerer at a time.** A second start finds `running.json`, asks the
  running one to come forward (`/api/focus`) and leaves. Requests to the
  local server go through no proxy: `launch.py` builds its opener with an
  empty `ProxyHandler`, since a system proxy would swallow 127.0.0.1.
- **In the browser there is no console to close Sourcerer with.** The page
  shows a Quit button there, and a detached Sourcerer without an open page
  stops after 15 minutes when no sync runs.
- **A venv is checked by running it, not by its file.** An interrupted first
  start leaves `python` without pip; after a Python upgrade or uninstall the
  venv points at an interpreter that is gone. `launch.py` runs `import pip` in
  it and rebuilds with `--clear` when that fails. The install stamp records the
  requirements' hash *and* the Python version.
- **One venv per system** (`venv/windows`, `venv/linux`, `venv/macos`): the
  folder is portable, and a venv one system built cannot run on another.
- **Every candidate Python must be 3.10+, not merely present.** An old
  `py -3` or `python3` must not hide a current one beside it.
- **In the `.bat`, every python that is not our own `.exe` is started with
  `call`.** A python that is itself a `.bat`/`.cmd` (pyenv-win's shims) would
  otherwise take over the launcher for good and never return. Exit codes are
  compared with `if "%errorlevel%"=="0"` — `if errorlevel 1` counts the
  negative codes of a crash as success. `setlocal` keeps the launcher's
  variables out of a console somebody opened themselves. No `cd`: from a
  `\\server` share cmd stays in `C:\Windows`; all paths are absolute.
- **The shell launchers are plain POSIX sh.** Started as `sh start-linux.sh`,
  dash misread bash's `&>` and reported an installed Python as missing.
- **macOS: `/usr/bin/python3` is a stub** until the Command Line Tools are
  installed — running it opens an install dialog. `start-macos.command` skips
  it then and also looks for Homebrew's and python.org's Python by path.
- **macOS blocks a downloaded `.command` once** (Gatekeeper). The README says
  how to allow it; the launcher cannot, since it never runs.
- **`.bat` stays CRLF, `.sh` / `.command` stay executable.** `.gitattributes`
  handles the line endings; the executable bit is git mode `100755` — check
  with `git ls-files -s start-*` after editing them on Windows.
- **No `( )` blocks around text with brackets in a `.bat`.** cmd expands a
  variable before it parses the block, so one `)` in a message ends the block
  early and the rest of the script never runs (TrackImage lost its whole start
  that way). Use plain `goto` labels, as `start-windows.bat` does.
- **The launchers find `Sourcerer_files/` from their own location** — through
  a symlink, too. Finder starts a `.command` in `$HOME`, Explorer may start a
  `.bat` anywhere; never rely on the current folder.
- **Nothing is written outside the folder.** pip's cache is pointed into
  `venv/pip-cache`; keep it that way when adding anything that caches.

### Program

- **Logins are made in Manage Accounts (`#dlg-accounts`) and nowhere else**:
  one box per login, the fields inside the box, no "add another" line --
  Mastodon, XenForo and Booru show one blank box (`SLOT` in `app.js`) only
  while no login of their kind exists. Settings has no Accounts pane. The
  toolbar button shows `S.logins` (the ones that ran out) as a red count.
- **The card dialog lists a site only when a login of it is saved**
  (`fields[].logged_in` in `/api/state`, an expired one counts) -- plus
  every link already on the card. Hiding a row must never drop a saved
  source: `renderSources` keeps a row with a link, `filledRows` still saves it.
- **`net.LOGIN` is only a message; code matches `net.LOGIN_PREFIX`.** Errors
  stored by older versions end differently, and the dot must still read them.
- **A new site is one module in `sourcerer/sources/`** with `KIND`, `LABEL`,
  `match(url)` and `pages(url)` yielding lists of `Media`, newest first, then
  added to `SITES`. Always fetch the original file, never a preview: Bluesky's
  CDN recompresses, so its files come from the account's PDS (`getBlob`).
- **`remote_key` is forever.** It decides whether a file is new; changing how
  a site builds it makes every file of that site download again.
- **A source's kind is recognised from its URL on every read**, not taken from
  the column: better detection then fixes sources saved before it.
- **Profile URLs lie about their site.** pixiv's `/users/123` matched the
  fediverse pattern; `mastodon.py` keeps a list of hosts that are not.
- **pywebview 6 turned `FOLDER_DIALOG` into a deprecated function.** Passing it
  as the dialog type opens nothing; use `FileDialog.FOLDER` (with a fallback
  for 5.x), as `server.pick_folder` does.
- **The same picture from two sources** is found by a 64-bit difference hash
  (`imaging.py`, Pillow): ≤ 5 differing bits is one picture. Only *across*
  sources — two similar posts on one site are usually two versions the artist
  meant. Per artist: `keep_all`, `best` (highest resolution, then the larger
  file; a better copy replaces a worse one already saved) or `master` (the
  master source's copy wins, synced first so nothing is replaced back and
  forth). Byte-identical files are kept once except under `keep_all`.
  Replacing deletes only a file Sourcerer itself saved.
- **Folder layout per artist:** `together` → `<library>/<artist>/`,
  `per_source` → `<library>/<artist>/<site>/`. A change applies to new files.
- **A sync scans first, then downloads**, so the card can show "downloading 87 / 240".
  Artists wait in a queue; cancelling stops after the current file. A source is
  marked complete only after a sync went all the way without a failure.
- **CSS class names are global.** `.empty` is the empty-state block (10vh
  margins): a status dot with that class grew 188 px tall; `.error:empty`
  (hide an empty form message) hid every `.dot.error`, which is always
  empty. Name modifiers for what they mean where they are (`.dot.blank`) and
  give page-wide rules an element (`p.error`).
- **No CDN, ever.** The icons are inline SVG drawn after Tabler Icons (MIT,
  `static/icons-LICENSE.txt`); fonts are the system's.
- **The server listens on 127.0.0.1 only.** Nothing here is for other machines.
  And only Sourcerer's own page may change anything (`server._same_origin`):
  any web page in the user's browser can POST a form to 127.0.0.1, so a
  POST with a foreign Origin or Host is refused. Requests without an Origin
  (launch.py's `/api/focus`) pass.
- **Be gentle with sites; it is what keeps users unblocked.** Every request
  goes through `net.py`: an honest User-Agent, at most `per_host` requests per
  site at once, `pace_ms` between them, Retry-After honoured; `HOSTS` makes a
  site stricter than Settings, `STOP_HOSTS` stops a source at the first 429
  instead of retrying (pixiv's terms). Never pretend to be a browser on a
  public API, never bypass `_Polite`, and give a login site gentler defaults
  than a public API -- there an account can be locked. The exceptions are
  deliberate: gallery-dl keeps its own browser emulation for X (a logged-in
  web session), and a forum's Cloudflare pass is sent with the login
  window's own User-Agent, which it is bound to.
- **A logged-in account is what gets banned, so a login has its own lane**
  (`net._Polite`, `login=True`): one request at a time, `LOGIN_PACE` after
  the previous one *ended* (a slow download must not let the next request
  follow at once), every gap times a random `JITTER`, a `READ_BREAK` every
  `READ_EVERY` requests, a daily `BUDGETS` count per site. Regular timing
  is what bot detection looks for -- never make a gap fixed again.
- **A site that objects rests, all of it** (`net.pause`, saved in the
  setting `paused`): a 429 on a login, a bot check, three refused logins,
  X's ratelimit or lock (gallery-dl `ratelimit: abort`, `_run`). A site is
  every host one company runs (`_SITES`): a stop from pixiv's API stops
  i.pximg.net too. Never retry into a 429 on a login -- that is how
  accounts get flagged; pause and let the next sync carry on.
- **One gallery-dl per site** (`_gdl._busy`): a gallery and a sync listing
  X at once looked like two clients on one session.
- **The gallery fetches only what a listing handed out.** The proxy
  (`/api/gallery/<gallery>/<n>/thumb|large`) takes an item number, never a
  URL: any page could otherwise make Sourcerer fetch with the user's
  logins. Its GETs check Host and `Sec-Fetch-Site` (`server._own_page`);
  pictures stay in memory (`gallery.MEMORY`), `no-store` to the web view.
  CDNs the page loads itself get `referrerpolicy="no-referrer"`.
- **The browser opens six connections to Sourcerer, no more.** Proxied
  pictures wait in a site's polite lane; fifty asked for at once held back
  the large view, the next page and the state poll for a minute. `app.js`
  loads them two at a time (`galQueue`), near the screen only; the large
  view shows the grid's picture until its own arrives.
- **Pikura is GPL-3.0.** Its gallery was studied for ideas (pixiv's small
  previews with a Referer); none of its code may be copied here.
- **The User-Agent is the crawler form** `Mozilla/5.0 (compatible;
  Sourcerer/<v>; +repo)`. pixiv's Cloudflare challenged any UA not starting
  with Mozilla/5.0 on logged-in requests.
- **Login cookies go as a Cookie header of their own**, never `cookies=`:
  requests sends those in addition to what the session caught, and pixiv
  read the guest PHPSESSID first -- a logged-in sync silently ran as a guest.
- **An expired login often fails silently.** Patreon's /api/posts answers an
  expired session_id as a guest; pixiv answers 401. Check the login itself
  (`patreon.whoami`, `sync._still_logged_in`) and mark it (`accounts.mark`);
  a login that ran out shows as a warning until renewed. Every start checks
  each saved login once (`sync.check_accounts_at_start`) and says the
  outcome in the activity log.
- **Originals, again:** Patreon's `image_urls.original` is a re-encode -- use
  the media's `download_url`. pixiv's original names often carry a hash
  that cannot be guessed (`<id>-<hash>_p0.jpg`): resolve them at download
  time (`Media.fetch`), never from thumbnails.
- **gallery-dl runs as a separate process** (`sources/_gdl.py`): it is
  GPL-2.0 and Sourcerer has no licence yet. It only lists (`-N prepare:`);
  cookies reach it through a mode-600 config file per run, never the command
  line; its cache (login state) lives in `Userdata/gallery-dl/`. An expired X
  session shows up as a login-page redirect and a bare "403 Forbidden".
- **Bot checks read the TLS handshake, not the headers.** baraag.net
  answered 403 and VerticalScope's forums 409 (`xf_is_suspected_bot`) or
  nothing to requests/urllib3 -- with any headers -- while curl passed:
  urllib3's handshake is the one every Python scraper makes. Python's own
  default context limited to TLS 1.3 passes (`net._Tls13`, and
  gallery-dl's `tls12: false` for forums). A host without TLS 1.3 is
  remembered in `net._OLD_TLS` (by host:port of the hop that failed, a
  redirect's too) and gets the usual handshake: at once when it refuses 1.3
  with an alert (gelbooru.com), only the second time when it hangs up (old
  Amazon balancers) -- one dropped handshake must not hand a bot-checked
  host the handshake it refuses for the rest of the run. It changes nothing
  about who Sourcerer says it is. A Cloudflare challenge (e926, some forums) is
  another matter: only a browser passes it -- the login window's
  `cf_clearance` for a forum.
- **Four ways to log in** (`accounts.kind`): `window` (cookies: X, Patreon,
  Pixiv, `xenforo:<host>`), `oauth` (Mastodon, `mastodon:<server>`: the
  server's own Authorize page in the login window, out-of-band redirect,
  read-only token), `password` (Bluesky: an app password opens a session;
  the account's real password is refused -- its JWT says
  `com.atproto.access` instead of `appPass`), `api_key` (`booru:<host>`).
  Cookies go to a site's hosts through `net.py`; tokens and keys are added
  by the site's module to its API requests only. A source names its login
  with `account_key(url)` and says how much it needs one with `LOGIN` /
  `login_need(url)`, which the card dialog shows under the link.
- **Boorus** (`sources/booru.py`): never fetch rule34.xxx itself (an image
  captcha) -- its API is api.rule34.xxx, its images wimg.rule34.xxx (api-cdn
  sometimes answers with a hotlink page; `net` refuses an HTML answer
  where a file should be). gelbooru.com answers its API only with a key
  (401, empty body); rule34 says "Missing authentication" with a 200.
  Danbooru allows two tags per search; page with `page=b<id>` and `id:<N`,
  never page numbers (capped at 1000). e926 is asked through e621.net
  with `rating:s`. Mirrors that share post ids and files (konachan.net,
  e926, safebooru.donmai.us) key their files as the main site
  (`SAME_POSTS`), so one post is one file. Moebooru gets no login: its
  API shows guests everything. realbooru's API is switched off. An old post
  can get the artist's tag years later, deep in the id order where the
  early stop never looks: booru sources are walked all the way once a week
  (`FULL_WALK_DAYS`, `sources.walked`).
- **A login is judged by the one that was used.** A check or sync stamps
  the login it read (`accounts.saved`) and `mark` ignores the result when a
  new login was saved meanwhile. A scan that went well proves nothing about
  a login: Mastodon and Bluesky read as a visitor when a token died, Patreon
  answers an expired session as a guest.
- **Bluesky allows only a few new sessions a day** (10 per identifier at
  the entryway). Never call createSession on your own: keep and rotate the
  refresh token; a dead one is an expired login, not a reason to log in
  again. Renew by the token's own lifetime (exp - iat from when it came),
  not the computer's clock, and once more on `ExpiredToken`.
- **A file already there is never downloaded again** (`sync._adopt`): the
  `archive` table keeps what deleted cards had, and a file under its own name
  in the card's folder (`_local_names`, `Media.local`) is taken over.
- **Never key a cached picture by row id alone.** SQLite hands out a deleted
  row's id again. Card pictures are made in memory from the downloads
  (`imaging.preview`, `?v=<sha>`); avatars are `Avatars/<artist>.jpg`.
- **A pasted link is normalised before it is stored.** `sources.normalize`
  turns any page of a profile (`/media`, a post) into the profile; dedupe
  happens after that. `remote_key` is untouched by it.
- **File names are the site's own** (`Media.filename`, else the server's
  Content-Disposition); Settings may put the date in front. Collisions get
  `_2`, `_3`.
- **A card's folder is `artists.folder`, or `<library>/<name>` when empty.**
  Always go through `sync.artist_folder(row)`, never build the path by hand.

### Updater

- **Never rename `Sourcerer_files/` as a whole.** v0.5's helper did, and on
  Windows a rename fails while anything holds a folder inside -- an Explorer
  window on the library (which lives in `Userdata/Library`), a virus
  scanner. The update silently never happened. The helper now moves the
  program's own items one by one (old ones to `Userdata/_update/old`, new
  ones in), never `Userdata/` or `venv/`, retries each move for 60 s and
  puts everything back when one fails.
- **On Windows two processes hold the program:** the app and the venv's
  `pythonw.exe`, a stub that runs the real interpreter as its child and waits
  for it. The helper waits for both (`getpid`, `getppid`). `launch.py` has
  left once Sourcerer answered.
- **A fix to the helper reaches users one version late:** the helper that
  runs is the installed version's. Somebody whose v0.5 helper failed has to
  put the new version in by hand once (README).
- **The helper runs on the system's Python, never the venv's**, and from the
  temp folder: both the venv and the program are in the folder it replaces.
- **The archive is checked before anything moves:** no absolute or `..`
  paths, the files in `REQUIRED` present, `VERSION` the one announced.
  GitHub's own archives (with their `Sourcerer-<ref>/` folder) are accepted
  for repair only.
- **Every step goes to `Userdata/Logs/update.log` the moment it happens**
  (v0.5 wrote it only at the end, so a helper that died left nothing), and
  every exit path restarts Sourcerer -- on Windows in a console of its own
  (`cmd /c` with CREATE_NEW_CONSOLE). The next start, also one by hand, puts
  the last run's outcome into the activity log once (`update_seen`). Simulated on
  Linux (swap, rollback, restart); the first real run on Windows and macOS is
  still to be watched.

## House style

Compact code, and comments that explain *why* — usually the thing that was
wrong before, so the next reader does not undo the fix. Match the surrounding
file; do not add a comment that only restates the line under it. JavaScript is
plain DOM code in `static/app.js`, no framework and no build step.

## Checks before pushing

There is no test suite yet. Run at least:

```bash
python3 -m py_compile .github/*.py Sourcerer_files/*.py Sourcerer_files/sourcerer/*.py Sourcerer_files/sourcerer/sources/*.py
node --check Sourcerer_files/static/app.js
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ('.github/workflows/version-bump.yml', '.github/workflows/release-zip.yml')]"
sh -n start-linux.sh && sh -n start-macos.command
sh ./start-linux.sh --no-open --port 8765   # the whole start; then use the page
```

`--browser` opens the browser instead of the window, `--no-open` only serves,
`--port` fixes the port; `SOURCERER_MAX_PAGES=1` keeps a test sync short.

`start-windows.bat` cannot be checked on Linux; after changing it, start it on
Windows once before pushing.

Never commit `__pycache__`, `Userdata/`, or anything the `.gitignore` names.
