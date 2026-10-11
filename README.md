# Sourcerer v0.5

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

**macOS, first start:** a script downloaded from the internet is blocked once.
Control-click `start-macos.command` › **Open** › **Open**. On macOS 15 and
later: double-click it once, then **System Settings › Privacy & Security ›
Open Anyway**.

## Use

1. **New card** (or the **+** tile) — paste the links of every place the
   artist posts. Any page of a profile works: `x.com/name/media`, a single
   post, the profile itself. The name and the profile picture come from the
   links; a dot per link says whether it answers (green), fails (red, with the
   reason) or is not supported yet (hollow). Per card: its folder (empty = one
   in your library), the layout (all together, or one folder per site) and what
   happens to the same picture from several sites — keep all, keep the best
   quality, or prefer one **master source**. **Create & sync** starts
   downloading at once, **Create** only saves the card.
2. **Sync all**, or the sync button on a card — the first sync fetches the
   whole history, later ones only what is new. Originals, not previews, under
   the file's own name. Cards wait in a queue; a running one can be cancelled.
   The bar at the bottom shows progress, speed and the queue; **Activity**
   opens the log.
3. **Settings** (the gear) — library folder, file names, automatic sync,
   parallel downloads, how gently sites are treated, theme, card size,
   updates (**Stable** or **Beta**) and repair.

A file you delete from the library is not downloaded again, and a file that
is already there is not downloaded twice: delete a card and make it again, or
point a card at a folder you collected by hand, and Sourcerer takes over what
it finds under the files' own names.

Shortcuts: `Ctrl+N` new card, `Ctrl+F` search, `F5` sync all, `Ctrl+,`
settings, arrow keys select a card, `Enter` edits it, `U` syncs it, `Del`
deletes it, `Ctrl` + mouse wheel sizes the cards, right-click opens a card's
menu. The full list is in Settings › Keyboard & mouse.

Sites downloaded today: **Bluesky**, **Mastodon** (and the fediverse),
**Pixiv**, **Patreon**, **X** and **XenForo** forums (a member's media
gallery, an album or a thread). Links to other sites stay on the card until
their site is supported. The dot beside each link says how it fares: green
works, yellow works with a catch (a login, a bot check, a site asking to slow
down), red does not work, grey is not checked yet.

**Accounts** (Settings › Accounts): X needs a login, Pixiv shows R-18 works
and Patreon a patron's posts only to a logged-in account, and many forums
show their media to members only. Log in once in Sourcerer's own window;
Sourcerer keeps that site's cookies on this computer, never the password.
When a login runs out, the bottom bar says so until you log in again.

## How Sourcerer talks to sites

Sourcerer reads posts through the interfaces the sites' own pages use — the
Mastodon API, Bluesky's AT Protocol, Pixiv's and Patreon's JSON — and says who
it is in every request (`Mozilla/5.0 (compatible; Sourcerer/<version>; +<this
repository>)`, the form search engines use). To stay far below what the
sites allow:

- at most 2 requests to one site at a time, with a pause between them
  (both adjustable in Settings › Sites & network), and stricter limits
  where a site asks for them: Pixiv one request every 1.5 s, Patreon one a
  second, X 1.5–3 s between pages;
- a "too many requests" answer is waited out for as long as the site asks —
  on Pixiv the sync stops and the next one carries on;
- a first sync of a big Pixiv or X account takes a few hundred files at a
  time and continues with the next sync;
- after the first sync, only the newest posts are looked at;
- automatic syncs start at a slightly different minute every time.

X is read with [gallery-dl](https://codeberg.org/mikf/gallery-dl), which keeps
up with X's ever-changing insides; Sourcerer updates it once a week (or in
Settings › Updates). A logged-in account is still an account that X can
lock: Sourcerer keeps its X traffic low and stops at once when X objects.

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
