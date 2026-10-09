# Sourcerer v0.0

[what changed](Sourcerer_files/docs/CHANGELOG.md) · [roadmap](Sourcerer_files/docs/ROADMAP.md) · [releases](../../releases)

A portable app for Windows, Linux and macOS that keeps per-artist media collections in sync across sites — XenForo Media Gallery, Mastodon, Patreon, Bluesky, X, Pixiv, DeviantArt and more — and drops every new file, de-duplicated across sources, straight into a [TrackImage](https://github.com/Moritz-arts/TrackImage) library.

**Status:** early development. There is no release yet.

## Install

1. Download **Source code (zip)** and unpack it into an **empty** folder.
2. Start it:

   | | |
   |---|---|
   | Windows | double-click `start-windows.bat` |
   | Linux | `./start-linux.sh` |
   | macOS | double-click `start-macos.command` |

The first start sets up a Python environment inside `Sourcerer_files/`. Nothing
is written outside the folder you unpacked into.

Needs Python 3.10 or newer.

## Layout

```
Sourcerer/
├─ start-windows.bat / start-linux.sh / start-macos.command
├─ README.md
└─ Sourcerer_files/
    ├─ app.py, VERSION, requirements.txt
    ├─ docs/        CHANGELOG.md, FOLDER_MAP.md, ROADMAP.md
    ├─ venv/        created on first start, never in an archive
    └─ Userdata/    your settings and logins, never touched by an update
```

`Sourcerer_files/docs/FOLDER_MAP.md` describes it in full. The repository also
holds the automation and the notes for whoever works on Sourcerer (`CLAUDE.md`,
`.github/`); those are kept out of the archive, so what you unpack is the
program and nothing else.
