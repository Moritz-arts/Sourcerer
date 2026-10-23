<p align="center">
  <a href="https://github.com/Moritz-arts/Sourcerer">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="Sourcerer_files/docs/brand/banner-dark.svg">
      <img alt="Sourcerer" src="Sourcerer_files/docs/brand/banner-light.svg" width="560">
    </picture>
  </a>
</p>

# Sourcerer v0.57

[What changed](Sourcerer_files/docs/CHANGELOG.md) · [Roadmap](Sourcerer_files/docs/ROADMAP.md) · [Releases](https://github.com/Moritz-arts/Sourcerer/releases)

**One card per artist, every place they post.** Sourcerer follows an artist across sites, shows all their
posts in one timeline, and downloads the originals into your library folder (a [TrackImage](https://github.com/Moritz-arts/TrackImage)
library works as it is) — each picture once, even if it is posted on several sites. Windows, macOS, Linux. Early development.

## Download

| System | Installer | Portable |
|---|---|---|
| **Windows** | [Sourcerer-Windows.exe](https://github.com/Moritz-arts/Sourcerer/releases/latest) | [Sourcerer-Windows.zip](https://github.com/Moritz-arts/Sourcerer/releases/latest) |
| **macOS** | [Sourcerer-macOS-arm64.dmg](https://github.com/Moritz-arts/Sourcerer/releases/latest) (Apple silicon) · [Sourcerer-macOS-x86_64.dmg](https://github.com/Moritz-arts/Sourcerer/releases/latest) (Intel) | – |
| **Linux** | [Sourcerer-Linux.AppImage](https://github.com/Moritz-arts/Sourcerer/releases/latest) | [Sourcerer-Linux.tar.gz](https://github.com/Moritz-arts/Sourcerer/releases/latest) (browser only) |

Nothing else to install. The files are not signed, so the first start shows a warning once:
**Windows** – *More info › Run anyway*. **macOS** – Control-click the app › *Open* (macOS 15: *System Settings ›
Privacy & Security › Open Anyway*). **Linux** – `chmod +x` the AppImage; it needs `libfuse2`.

<details>
<summary>With Python instead (<b>Sourcerer.zip</b>, updates itself)</summary>

Needs Python 3.10+. Unpack [Sourcerer.zip](https://github.com/Moritz-arts/Sourcerer/releases/latest/download/Sourcerer.zip)
(not GitHub's green *Code* button), then start `start-windows.bat`, `./start-linux.sh` or `start-macos.command`.
The first start builds a Python environment inside the folder; nothing is written elsewhere.
On macOS the script is blocked once: Control-click › *Open*.
</details>

## Use it

1. **Add an artist.** Paste the links of every place they post — any page of a profile works. A dot per link
   shows whether it answers. Per card you choose a folder, one folder or one per site, and what happens to the
   same picture from several sites (keep all, keep the best, or prefer one *master source*).
2. **Log in where a site needs it** (**Manage Accounts**). With *Import follows* on, the accounts a login follows
   appear as cards by themselves — nothing is downloaded until you ask.
3. **Browse.** The artist list is on the left, their posts on the right, newest first, straight from the sites;
   **All artists** is one timeline over everyone. Three views: **Artists** (overview), **Gallery**, **Recommended** (coming).
4. **Refresh** looks for new posts and says how many are missing. **Download** fetches them. Turn on
   **Auto-download** for an artist (a green cloud in the list) and a refresh downloads by itself.

Files keep the name the site gives them. A file you deleted is not downloaded again; one already in the folder
is taken over, not copied twice. Two cards of the same artist can be merged (*Merge into…*, *Merge sources*).

<details>
<summary>Keys</summary>

`↑` `↓` pick an artist · `Enter` edit · `A` auto-download · `U` refresh · `D` download · `O` open folder ·
`M` merge · `F` favorite · `Del` delete · `F5` refresh all · `Ctrl+F` search · `Ctrl+,` settings ·
in a picture: `←` `→` step, `D` download, `O` open post, `Esc` close · `Ctrl` + wheel sizes the pictures.
Full list: *Settings › Keyboard & mouse*.
</details>

## Sites

| Site | Login |
|---|---|
| **Bluesky** | app password (not your real password) |
| **Mastodon**, **Misskey** (fediverse) | only for members-only servers |
| **Pixiv** | for R-18 works |
| **Patreon**, **Fanbox**, **Fantia** | yes |
| **X** | yes |
| **XenForo** forums (media gallery, albums, threads) | usually yes |
| **Boorus** – Danbooru, e621, Gelbooru, Rule 34, yande.re, Konachan … (an artist's tag search) | API key for some |

Logins open the site's own login page inside Sourcerer. Sourcerer keeps cookies or read-only tokens in
`Userdata/`, never a password. It talks only to the sites you add and to GitHub for updates.

## Data and updates

| Version | Your data (cards, logins, settings, library) |
|---|---|
| Windows, Linux tar.gz | the `Userdata` folder next to the program |
| macOS | `~/Library/Application Support/Sourcerer` (downloads: `~/Pictures/Sourcerer`) |
| Linux AppImage | `~/.local/share/Sourcerer` |
| With Python | `Sourcerer_files/Userdata` |

*Settings › Updates* tells you when a release is out. **Stable** is the latest release, **Beta** is the newest `main`.
Installed Windows copy: **Install** does everything. macOS, AppImage, portable: replace the app or file — your data stays.
Copy the data folder to back everything up.

## Gentle with sites

Sourcerer says who it is (`Sourcerer/<version>` in every request) and keeps its traffic small, slow and irregular:
a few requests at a time with pauses; logged-in accounts get one request at a time with random gaps, reading
breaks and a daily budget; a site that objects (too many requests, bot check, locked account) rests for hours;
after the first sync only the newest posts are read. This does not make scraping something every site's terms
allow — it keeps accounts out of trouble in practice. X, forums, Fanbox and Fantia are read with
[gallery-dl](https://codeberg.org/mikf/gallery-dl), which Sourcerer updates weekly.

## For developers

```
Sourcerer/
├─ start-windows.bat · start-linux.sh · start-macos.command
├─ README.md
└─ Sourcerer_files/   the program, its docs and your data
```

[Folder map](Sourcerer_files/docs/FOLDER_MAP.md) · notes for contributors in `.claude/CLAUDE.md` (not in the download).
