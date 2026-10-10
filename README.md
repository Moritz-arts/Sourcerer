# Sourcerer v0.2

[what changed](Sourcerer_files/docs/CHANGELOG.md) · [roadmap](Sourcerer_files/docs/ROADMAP.md) · [releases](https://github.com/Moritz-arts/Sourcerer/releases)

A portable app for Windows, Linux and macOS that keeps per-artist media collections in sync across sites — XenForo Media Gallery, Mastodon, Patreon, Bluesky, X, Pixiv, DeviantArt and more — and drops every new file, de-duplicated across sources, straight into a [TrackImage](https://github.com/Moritz-arts/TrackImage) library.

**Status:** early development. There is no release yet.

## Install

1. Download **Sourcerer.zip** and unpack it (Windows: right-click › **Extract
   All**). You get one folder, `Sourcerer`, with everything in it — move it
   wherever you like.

   | | |
   |---|---|
   | **Stable** | [Sourcerer.zip from the latest release](https://github.com/Moritz-arts/Sourcerer/releases/latest/download/Sourcerer.zip) — versions declared finished (from the first release on) |
   | **Beta** | [Sourcerer.zip, newest build](https://github.com/Moritz-arts/Sourcerer/releases/download/beta/Sourcerer.zip) — every change, minutes after it is merged; untested |

   Not the green **Code › Download ZIP** button: GitHub wraps that one in an
   extra `Sourcerer-main` folder.
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

## Use

1. **+ Karte** — the artist's name and the links of every place they post.
   Mastodon (and the fediverse) and Bluesky are downloaded today; other links
   stay on the card until their site is supported. Per card you choose the
   folder layout (all together, or one folder per site) and what happens to the
   same picture from several sites: keep all, keep the best quality, or prefer
   one **master source**.
2. **Aktualisieren** on a card, or **Alle aktualisieren** — the first sync
   fetches the whole history, later ones only what is new. Originals, not
   previews. Cards wait in a queue; a running one can be cancelled.
3. **Settings** (the gear) — the library folder. Every artist gets a folder in
   it; link it in TrackImage and new files appear there by themselves.

A file you delete from the library is not downloaded again.

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
