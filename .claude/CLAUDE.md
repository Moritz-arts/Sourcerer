# Working on Sourcerer

A portable app for Windows, Linux and macOS that keeps per-artist media
collections in sync across sites and drops every new file, de-duplicated across
sources, into a [TrackImage](https://github.com/Moritz-arts/TrackImage) library. Sibling
project of TrackImage, built the same way: the repository *is* the program —
what people download and unpack is these folders, unchanged.

**Status: early development.** What exists: the three launchers with
`launch.py` behind them, a placeholder `app.py`, and the workshop — these notes, the docs and the automation that
versions every push.

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
   `Sourcerer_files/docs/CHANGELOG.md`. GitHub's own source archive is the
   release — no uploaded files.

Do not create releases or tags yourself, and do not push to `main`.

## Traps

### Sourcerer's own

- **`Sourcerer_files/Userdata/` holds logins, tokens and cookies.** It is
  git-ignored and must stay that way. Never commit it, never write its
  contents to a log, never put a credential into a commit message, an issue or
  a test fixture.

### Inherited from TrackImage — they apply here as soon as the updater exists

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
- **Everything here is written in English — file and folder names included.**

### Launchers

- **The launchers only find Python; `launch.py` does the rest.** Each launcher
  looks for a Python 3.10+ in its system's way and hands over to
  `Sourcerer_files/launch.py`, which builds the environment, installs the
  packages and starts `app.py` — once, in Python, testable on any system.
  Anything more goes into `launch.py`, not into three shell languages that
  drift apart. Packages live in `Sourcerer_files/requirements.txt`.
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

## House style

Compact code, and comments that explain *why* — usually the thing that was
wrong before, so the next reader does not undo the fix. Match the surrounding
file; do not add a comment that only restates the line under it.

## Checks before pushing

There is no test suite yet. Run at least:

```bash
python3 -m py_compile .github/*.py Sourcerer_files/*.py
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/version-bump.yml'))"
sh -n start-linux.sh && sh -n start-macos.command
sh ./start-linux.sh   # the whole start, end to end -- twice: build, then reuse
```

`start-windows.bat` cannot be checked on Linux; after changing it, start it on
Windows once before pushing.

Never commit `__pycache__`, `Userdata/`, or anything the `.gitignore` names.
