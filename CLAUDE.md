# Working on Sourcerer

A portable app for Windows, Linux and macOS that keeps per-artist media collections in sync across
sites and drops every new file, de-duplicated across sources, into a
[TrackImage](https://github.com/Moritz-arts/TrackImage) library. Sibling
project of TrackImage, built the same way: the repository *is* the program —
what people download and unpack is these folders, unchanged.

**Status: early development.** What exists: the three launchers, a placeholder
`app.py`, and the workshop — these notes, the docs and the automation that
versions every push.

## Where the knowledge lives

Everything somebody needs to carry on — with or without Claude — is in the
repository, never only in a chat:

| File | What it holds | Who keeps it current |
|---|---|---|
| `CLAUDE.md` | rules, traps, house style, checks | whoever learns something |
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

The repository root stays short on purpose — README.md, CLAUDE.md and the
three launchers (`start-windows.bat`, `start-linux.sh`, `start-macos.command`).
Everything else lives in `Sourcerer_files/`, `docs/` and all machine state
(`venv/`, `Userdata/`) included. Do not add another file beside the launchers.

**What people download is not what the repository holds.** `.gitattributes`
marks the workshop files `export-ignore`, so `.github/`, `CLAUDE.md` and the
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
start-windows.bat / start-linux.sh / start-macos.command
                            Sourcerer v0.1 - Setup & Start
```

The program reads its version from `Sourcerer_files/VERSION` and from nowhere
else; do not spell the number out in code. A new place that prints it goes into
`PLACES` in `.github/bump_version.py`. If a change genuinely must not raise the
version, put `[skip version]` in the commit message.

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
   (`v0.1`), and pushes. It does **not** publish a release.
4. When the user judges a version ready, they draft a release from its tag by
   hand and paste that version's section out of
   `Sourcerer_files/docs/CHANGELOG.md`. GitHub's own source archive is the
   release — no uploaded files.

Do not create releases or tags yourself, and do not push to `main`.

## Traps

### Sourcerer's own

- **`Sourcerer_files/Userdata/` holds logins, tokens and cookies.** It is
  git-ignored and must stay that way. Never commit it, never write its contents to a log, never put
  a credential into a commit message, an issue or a test fixture.

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
- **A backup belongs to the user.** Move old backups, never delete them as a
  "tidy-up"; keep a fixed number of recent ones.
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

- **Three launchers, one behaviour.** A change to one goes into all three in the
  same commit. Dependencies live in `Sourcerer_files/requirements.txt`, never
  in a launcher, so there is one list rather than three that drift apart.
- **`.bat` stays CRLF, `.sh` / `.command` stay executable.** `.gitattributes`
  handles the line endings; the executable bit is git mode `100755` — check
  with `git ls-files -s start-*` after editing them on Windows.
- **No `( )` blocks around text with brackets in a `.bat`.** cmd expands a
  variable before it parses the block, so one `)` in a message ends the block
  early and the rest of the script never runs (TrackImage lost its whole start
  that way). Use plain `goto` labels, as `start-windows.bat` does.
- **The launchers find `Sourcerer_files/` from their own location.** Finder
  starts a `.command` in `$HOME`, Explorer may start a `.bat` anywhere; never
  rely on the current folder.

## House style

Compact code, and comments that explain *why* — usually the thing that was
wrong before, so the next reader does not undo the fix. Match the surrounding
file; do not add a comment that only restates the line under it.

## Checks before pushing

There is no test suite yet. Run at least:

```bash
python3 -m py_compile .github/*.py $(git ls-files 'Sourcerer_files/*.py')
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/version-bump.yml'))"
bash -n start-linux.sh && bash -n start-macos.command
./start-linux.sh      # the whole start, end to end
```

`start-windows.bat` cannot be checked on Linux; after changing it, start it on
Windows once before pushing.

Never commit `__pycache__`, `Userdata/`, or anything the `.gitignore` names.
