# Sourcerer — folder map

Keep this file in step with the tree: a file added, moved or dropped is
described here in the same commit. Entries marked *planned* do not exist yet.

```
Sourcerer/                        <- what the ZIP unpacks to
├─ start-windows.bat              the launchers -- the only things the user starts
├─ start-linux.sh
├─ start-macos.command
├─ README.md
└─ Sourcerer_files/               everything Sourcerer owns
    ├─ app.py                     entry point; the launchers start this and nothing else
    ├─ VERSION                    the version -- the one place it is defined
    ├─ requirements.txt           the packages, one list for all three systems
    ├─ sourcerer/                 planned -- the Python package
    ├─ docs/
    │   ├─ CHANGELOG.md           written by the workflow, never by hand
    │   ├─ FOLDER_MAP.md          this file
    │   └─ ROADMAP.md             goal, sources, decisions, done / next
    │
    ├─ venv/                      NOT shipped -- the launcher builds it on first start
    └─ Userdata/                  NOT shipped -- settings, logins, tokens, cookies, logs
```

Only in the repository, never in an archive (`export-ignore` in `.gitattributes`):

```
├─ CLAUDE.md                      rules and traps for whoever works on it
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
- `venv/` and `Userdata/` belong to the machine. They sit inside
  `Sourcerer_files/`, which an update will replace whole, so the updater must
  carry both across — never take them from an archive, never overwrite them.
- The launchers find `app.py` relative to their own location, so the folder
  can live anywhere and be renamed freely.
- The version lives in `Sourcerer_files/VERSION`. The README title and the
  three launcher banners are copies the workflow keeps in step.
