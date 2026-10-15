# Sourcerer v0.9

[what changed](Sourcerer_files/docs/CHANGELOG.md) · [roadmap](Sourcerer_files/docs/ROADMAP.md) · [releases](https://github.com/Moritz-arts/Sourcerer/releases)

A portable app for Windows, Linux and macOS that keeps per-artist media collections in sync across sites — XenForo Media Gallery, Mastodon, Patreon, Bluesky, X, Pixiv, boorus and more — and drops every new file, de-duplicated across sources, straight into a [TrackImage](https://github.com/Moritz-arts/TrackImage) library.

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

**If an update does not go through** (Sourcerer closes and comes back as
the old version): close every Explorer/Finder window showing a folder inside
`Sourcerer_files`, then try again — Settings › Updates shows what went wrong.
From v0.5 by hand: unpack the new Sourcerer.zip, and move the folders
`Userdata` (your cards, logins and library) and `venv` from the old
`Sourcerer_files` into the new one.

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
3. **Gallery** (the picture button on a card, `G`, or the card's menu) —
   everything the card's sources show, merged into one stream, newest
   first, straight from the sites: nothing is saved unless you ask. Scroll
   and it asks the sites for more; click a picture to see it large (arrow
   keys step through), **Download** puts that one file into the card's
   folder the way a sync would, **Open post** opens it on the site. The
   chips at the top show or hide a source. Most pictures come from the
   sites' own image servers; those that need a login or a Referer (Pixiv,
   Gelbooru, forums) are fetched by Sourcerer and kept in memory only.
4. **Settings** (the gear) — library folder, file names, automatic sync,
   parallel downloads, how gently sites are treated, theme, card size,
   updates (**Stable** or **Beta**) and repair.

A file you delete from the library is not downloaded again, and a file that
is already there is not downloaded twice: delete a card and make it again, or
point a card at a folder you collected by hand, and Sourcerer takes over what
it finds under the files' own names.

Shortcuts: `Ctrl+N` new card, `Ctrl+F` search, `F5` sync all, `Ctrl+,`
settings, arrow keys select a card, `Enter` edits it, `U` syncs it, `G` opens its
gallery, `Del` deletes it, `Ctrl` + mouse wheel sizes the cards, right-click opens a card's
menu. The full list is in Settings › Keyboard & mouse.

Sites downloaded today: **Bluesky**, **Mastodon** (and the fediverse),
**Pixiv**, **Patreon**, **X**, **XenForo** forums (a member's media
gallery, an album or a thread) and **boorus** — Danbooru, e621, Gelbooru,
Rule 34, Safebooru, yande.re, Konachan and others — where a source is the
artist's tag search (`danbooru.donmai.us/posts?tags=artist_name`; an
artist's page or one of their posts works too). Links to other sites stay
on the card until their site is supported. The dot beside each link says how it fares: green
works, yellow works with a catch (a login, a bot check, a site asking to slow
down), red does not work, grey is not checked yet.

**Manage Accounts** (the button beside *Sync all*) has a box for every site, with a dot
that says whether its login works. X needs
one, Pixiv shows R-18 works and Patreon a patron's posts only to a
logged-in account, many forums and some Mastodon servers show their media
to members only, and Gelbooru and Rule 34 answer only to an API key.

- X, Patreon, Pixiv, forums and Mastodon servers: the site's own login page
  opens in Sourcerer's window (Mastodon then asks you to let Sourcerer
  read). Sourcerer keeps the site's cookies or its read-only token.
- Bluesky: your handle and an **app password** (Bluesky › Settings ›
  Privacy and security › App passwords) — never your account's password.
- Boorus: your user name (Gelbooru, Rule 34: user ID) and the API key from
  your account settings; for Gelbooru and Rule 34, paste the whole
  `&api_key=…&user_id=…` line.

Everything stays on this computer, and no password is kept. The card dialog
lists only the sites you are logged in to; a link already on a card stays
even when its login is gone, and says so with a button to log in. Every
start checks all logins; when one runs out, the *Manage Accounts* button
turns red and the bottom bar says so until you log in again.

## How Sourcerer talks to sites

Sourcerer reads posts through the interfaces the sites' own pages use — the
Mastodon API, Bluesky's AT Protocol, Pixiv's and Patreon's JSON, the boorus'
APIs — and says who
it is in every request (`Mozilla/5.0 (compatible; Sourcerer/<version>; +<this
repository>)`, the form search engines use). To stay far below what the
sites allow:

- at most 2 requests to one site at a time, with a pause between them
  (both adjustable in Settings › Sites & network), and stricter limits
  where a site asks for them: Pixiv one request every 1.5 s, Patreon, e621,
  Gelbooru and the other boorus one a second, X 2–4 s between pages;
- a request that carries a login waits its turn alone: at least 2 s after
  the previous one *ended*, every gap stretched by a random 0–60 %, and a
  break of 15–60 s every 20–40 requests — the rhythm of somebody reading,
  not of a script;
- each logged-in site has a daily budget (Pixiv, Patreon and X 1,500
  requests); what is left waits for the next day;
- when a site objects — "too many requests", a bot check, a refused login
  three times running, X saying the account is limited or locked — that
  site rests for hours (X a day or two after a lock), saved across restarts
  and shown in the bottom bar; the rest of Sourcerer carries on;
- a first sync of a big Pixiv, X or booru account takes a few hundred files
  at a time and continues with the next sync;
- after the first sync, only the newest posts are looked at;
- automatic syncs come at a random time within the interval, take the cards
  that waited longest first, leave a logged-in site alone for hours between
  them (X 12, Pixiv and Patreon 6) and let 20–90 s pass between two cards on
  the same site; logins are checked spread out, not all at once.

None of this makes scraping something X's or Pixiv's terms allow; it keeps
Sourcerer's traffic small, slow and irregular, which is what keeps accounts
out of trouble in practice. The gallery goes through the same limits.

X is read with [gallery-dl](https://codeberg.org/mikf/gallery-dl), which keeps
up with X's ever-changing insides; Sourcerer updates it once a week (or in
Settings › Updates). A logged-in account is still an account that X can
lock: Sourcerer keeps its X traffic low (one gallery-dl at a time, a 2–4 s
pause between pages) and stops at once when X objects.

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
