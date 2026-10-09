# Sourcerer — folder map

Keep this file in step with the tree: a file added, moved or dropped is
described here in the same commit. Entries marked *planned* do not exist yet.

```
Sourcerer/                        <- what the ZIP unpacks to
├─ start-windows.bat              planned — the only thing the user should start
├─ README.md
└─ Sourcerer_files/               everything Sourcerer owns; swapped whole by an update
    ├─ VERSION                    the version — the one place it is defined
    └─ docs/
        ├─ CHANGELOG.md           written by the workflow, never by hand
        ├─ FOLDER_MAP.md          this file
        └─ ROADMAP.md             goal, sources, done / next

Created on the machine, never shipped, never in git (see .gitignore):
├─ Userdata/                      settings, logins, tokens, cookies, logs
├─ runtime/                       the portable Python environment
├─ _update/                       only exists while an update installs
└─ Sourcerer_files.bak/           the previous version, kept until the swap succeeded
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

- An update replaces `Sourcerer_files/` and nothing else. `Userdata/` and
  `runtime/` are machine state and are never touched by an update.
- The version lives in `Sourcerer_files/VERSION`. The README title and the
  launcher banner are copies the workflow keeps in step.
