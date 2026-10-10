# Sourcerer v0.1

[what changed](Sourcerer_files/docs/CHANGELOG.md) · [roadmap](Sourcerer_files/docs/ROADMAP.md) · [releases](https://github.com/Moritz-arts/Sourcerer/releases)

A portable app for Windows, Linux and macOS that keeps per-artist media collections in sync across sites — XenForo Media Gallery, Mastodon, Patreon, Bluesky, X, Pixiv, DeviantArt and more — and drops every new file, de-duplicated across sources, straight into a [TrackImage](https://github.com/Moritz-arts/TrackImage) library.

**Status:** early development. There is no release yet.

## Install

1. Download the ZIP — **Code › Download ZIP** on GitHub, or **Source code (zip)**
   from a release once there is one — and unpack it. It holds a single folder
   (`Sourcerer-main` or `Sourcerer-<version>`); rename it to `Sourcerer` if you
   like and put it wherever you want.
2. Start it:

   | | |
   |---|---|
   | Windows | double-click `start-windows.bat` |
   | Linux | `./start-linux.sh` in a terminal |
   | macOS | double-click `start-macos.command` |

The first start sets up a Python environment inside `Sourcerer_files/`. Nothing
is written outside the folder.

Needs Python 3.10 or newer — on Windows from [python.org](https://www.python.org/downloads/),
on macOS from python.org or Homebrew (`brew install python`).

**macOS, first start:** a script downloaded from the internet is blocked once.
Control-click `start-macos.command` › **Open** › **Open**. On macOS 15 and
later: double-click it once, then **System Settings › Privacy & Security ›
Open Anyway**.

## Layout

```
Sourcerer/
├─ start-windows.bat / start-linux.sh / start-macos.command
├─ README.md
└─ Sourcerer_files/   everything else -- the program, its docs, your data
```

`Sourcerer_files/docs/FOLDER_MAP.md` describes it in full. The repository also
holds the automation and the notes for whoever works on Sourcerer (`.github/`,
`.claude/`); those are kept out of the ZIP, so what you unpack is the program
and nothing else.
