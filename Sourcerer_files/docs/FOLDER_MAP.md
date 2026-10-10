# Sourcerer — folder map

Keep this file in step with the tree: a file added, moved or dropped is
described here in the same commit. Entries marked *planned* do not exist yet.

```
Sourcerer-<version>/              <- what the ZIP unpacks to; rename it freely
├─ start-windows.bat              the launchers: find a Python 3.10+, hand over
├─ start-linux.sh                   to launch.py -- the only things a user starts
├─ start-macos.command
├─ README.md
└─ Sourcerer_files/               everything Sourcerer owns
    ├─ launch.py                  shared by all three launchers: environment,
    │                               packages, then app.py
    ├─ app.py                     the program's entry point
    ├─ VERSION                    the version -- the one place it is defined
    ├─ requirements.txt           the packages, one list for all three systems
    ├─ sourcerer/                 planned -- the Python package
    ├─ docs/
    │   ├─ CHANGELOG.md           written by the workflow, never by hand
    │   ├─ FOLDER_MAP.md          this file
    │   └─ ROADMAP.md             goal, sources, decisions, done / next
    │
    ├─ venv/                      NOT shipped -- launch.py builds it on first start
    │   ├─ windows/ linux/ macos/   one environment per system that started it
    │   └─ pip-cache/               pip's downloads, kept out of the user's home
    └─ Userdata/                  NOT shipped, planned -- settings, logins,
                                    tokens, cookies, logs, backups
```

Only in the repository, never in the ZIP (`export-ignore` in `.gitattributes`):

```
├─ .claude/CLAUDE.md              rules and traps for whoever works on it
├─ .github/
│   ├─ workflows/version-bump.yml raises the version on every push to main
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
