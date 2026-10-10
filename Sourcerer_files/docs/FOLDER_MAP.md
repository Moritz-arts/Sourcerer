# Sourcerer — folder map

Keep this file in step with the tree: a file added, moved or dropped is
described here in the same commit. Entries marked *planned* do not exist yet.

```
Sourcerer/                        <- what Sourcerer.zip unpacks to; move it freely
├─ start-windows.bat              the launchers: find a Python 3.10+, hand over
├─ start-linux.sh                   to launch.py -- the only things a user starts
├─ start-macos.command
├─ README.md
└─ Sourcerer_files/               everything Sourcerer owns
    ├─ launch.py                  shared by all three launchers: environment,
    │                               packages, then app.py
    ├─ app.py                     the program's entry point: sourcerer.desktop.main()
    ├─ VERSION                    the version -- the one place it is defined
    ├─ requirements.txt           the packages, one list for all three systems
    ├─ sourcerer/                 the Python package; layers listed in __init__.py
    │   ├─ config.py              paths, version, user agent, setting defaults
    │   ├─ db.py                  SQLite: artists, sources, files, settings
    │   ├─ net.py                 HTTP (requests): JSON, downloads, per-site limits
    │   ├─ imaging.py             fingerprints, sizes, thumbnails, avatars (Pillow)
    │   ├─ sources/               one module per site
    │   │   ├─ __init__.py        Media, site_for, normalize, describe, profile
    │   │   ├─ mastodon.py        Mastodon / fediverse, public API
    │   │   └─ bluesky.py         Bluesky, public API, original blobs
    │   ├─ sync.py                sync queue, scan then download, dedupe, folders,
    │   │                           automatic sync, link checks, profile pictures
    │   ├─ updater.py             updates and repair: Sourcerer.zip, the helper
    │   ├─ server.py              Flask: /api/* and the page
    │   └─ desktop.py             main(): server thread, window or browser
    ├─ static/                    the page: index.html, app.css, app.js,
    │                               logo.svg (also the favicon),
    │                               icons-LICENSE.txt (inline icons after Tabler)
    ├─ docs/
    │   ├─ CHANGELOG.md           written by the workflow, never by hand
    │   ├─ FOLDER_MAP.md          this file
    │   └─ ROADMAP.md             goal, sources, decisions, done / next
    │
    ├─ venv/                      NOT shipped -- launch.py builds it on first start
    │   ├─ windows/ linux/ macos/   one environment per system that started it
    │   └─ pip-cache/               pip's downloads, kept out of the user's home
    └─ Userdata/                  NOT shipped -- created on first start
        ├─ sourcerer.db           artists, sources, every file seen, settings
        ├─ Logs/                  sourcerer.log; update.log (the update helper's
        │                           steps); console.log (a restart's output, Linux)
        ├─ Thumbs/                card thumbnails, rebuilt when missing
        ├─ Avatars/               profile pictures, <card id>.jpg
        ├─ _update/               an update being unpacked; gone after the swap
        ├─ rebuild-venv           left by Settings › Repair; launch.py rebuilds
        │                           the environment and removes it
        └─ Library/               downloads, one folder per artist (and one per
                                    site inside it, if the card says so) -- until
                                    another library folder is chosen in Settings
```

Only in the repository, never in the ZIP (`export-ignore` in `.gitattributes`):

```
├─ .claude/CLAUDE.md              rules and traps for whoever works on it
├─ .claude/design/                the original design mockups the window follows
├─ .github/
│   ├─ workflows/version-bump.yml raises the version on every push to main,
│   │                               and puts that build on the `beta` prerelease
│   ├─ workflows/release-zip.yml  attaches Sourcerer.zip to a published release
│   ├─ bump_version.py            rewrites the number everywhere it is written
│   └─ changelog_entry.py         turns commit subjects into the changelog entry
├─ .gitattributes
└─ .gitignore
```

## Rules that follow from this layout

- The root holds the three launchers, README.md and `Sourcerer_files/` —
  nothing else ships there. Everything new goes into `Sourcerer_files/`.
- The launchers stay thin: finding Python differs per system, everything after
  that lives in `launch.py`, once.
- `venv/` and `Userdata/` belong to the machine. They sit inside
  `Sourcerer_files/`, which an update will replace whole, so the updater must
  carry both across — never take them from an archive, never overwrite them.
- The launchers find `Sourcerer_files/` from their own location, so the folder
  can live anywhere and be renamed freely.
- The version lives in `Sourcerer_files/VERSION`. The README title is a copy
  the workflow keeps in step; `launch.py` prints it from the file.
