# Sourcerer — roadmap

Where the project is, what is decided, what comes next. Update it in the same commit as the work that changes it.
The details of *how* things work are in `.claude/CLAUDE.md`; the history is in [CHANGELOG.md](CHANGELOG.md).

## Goal

A portable app for Windows, Linux and macOS that keeps per-artist media collections in sync across sites and
drops every new file, de-duplicated across sources, into a [TrackImage](https://github.com/Moritz-arts/TrackImage) library.

## Sites

| Site | Status | Notes |
|---|---|---|
| Bluesky | works | public posts, original files incl. video; login: app password |
| Mastodon and the fediverse | works | originals; login (OAuth, read-only) for members-only servers |
| Misskey | works | notes with files; login (MiAuth) per server |
| Pixiv | works | R-18 with a login; ugoira plays as an animated WebP |
| Patreon | works | originals; patron posts with a login |
| Fanbox, Fantia | works | cookie login |
| X | works with a login | listed by gallery-dl, originals |
| XenForo forums | works | media gallery or attachment browser, albums, threads; login per forum; forums behind a guard or in a folder work |
| Boorus | works | Danbooru, e621, Gelbooru, Rule 34, yande.re, Konachan and more: an artist's tag search |
| DeviantArt | not started | |

## Decisions

- **Stack:** Flask on 127.0.0.1, a pywebview window (the browser when none can open), plain JavaScript, SQLite in `Userdata/`.
- **Python version and standalone version side by side:** the launchers use the system Python (3.10+) and a `venv`;
  the standalone downloads (installer, .dmg, AppImage, portable files) have Python inside. Both are built from this repository.
- **Versions and the changelog are automatic:** a workflow raises the version on every push to `main`, tags it and writes
  the changelog from the commit subjects. A release is made on command (*Actions › Publish*).
- **Stable is the latest release, Beta is `main`.** No prereleases.
- **English everywhere,** the interface included.
- **gallery-dl runs as a separate process** for X, forums, Fanbox and Fantia (its licence stays apart from Sourcerer's; it can be
  upgraded between releases). Pixiv, Patreon, Mastodon, Misskey, Bluesky and the boorus use Sourcerer's own code on the sites' JSON.
- **Gentle with sites, always:** an honest User-Agent, few parallel requests, logins in their own slow lane with random gaps,
  daily budgets, a site that objects rests for hours. Protecting accounts comes before speed.
- **Sourcerer stores no pictures of its own:** thumbnails, previews and profile pictures live in memory only.
- **Refresh and Download are separate.** Refresh looks (and keeps the newest posts as snapshots), Download fetches.
  Each artist has an Auto-download switch.
- **Browse opens from snapshots** and checks the site meanwhile. *All artists* never asks a login site: it shows the snapshots,
  and *Refresh all* reads the sites.
- **Followed accounts become cards** (only *listed*, in no sweep until you touch them). The same artist on several sites is combined
  by evidence — what profiles name, then the account name, then the display name — and every suggestion says why; "Not the same" is kept.
- **Originals, under the site's own file names.** The same picture from two sites is found by a difference hash; each artist
  chooses keep all, best quality or master source. A file already there is never downloaded again.
- **No warning boxes.** An action is undone by a way back (backups, login files), not by a question.
- **Updates:** the Python version swaps its own folder (user data and `venv` carried over, old version restored on failure);
  an installed Windows copy updates through its installer; other standalone copies are replaced by hand.
- **Downloads are unsigned** for now (SmartScreen and Gatekeeper warn once).
- **Brand:** one identity across app, installer, icons and this repository (brand guide in `docs/brand/`).

## Done

**Core** — window, artist cards, background sync with queue, progress and log, original file names, parallel downloads,
settings (library, file names, automatic sync, speed, theme, updates, repair, security with a master password and reset).

**Sites and logins** — every site above; one login per site in *Manage Accounts* (cookies, OAuth, app password, API key),
checked at every start; a login that ran out is flagged.

**Follows** — the accounts a login follows become cards (Bluesky, Mastodon, Misskey, pixiv, Fanbox, Fantia, X, Patreon, XenForo);
the same artist on several sites is combined; merge dialogs with reasons, *Merge sources*, favorites; cards are named by the artist's @name.

**Browse** — three views (Artists, Gallery, Recommended placeholder); artists on the left, posts on the right; *All artists* with a time window;
site chips, Squares / Full layout, viewer with zoom, download one / several / whole artist, GIFs and ugoira play; settings of the page are kept across restarts.

**Speed and safety** — snapshots, one cached listing per artist, a pooled picture session, indexes on the file table; request counting per site,
look gaps for sources read lately, rate-limit windows respected, three artists on different sites at once.

**Downloads and updates** — Sourcerer-Windows.exe and portable zip, .dmg for both Mac types, AppImage and tar.gz, built and started by CI before they are attached;
in-app update for the Python version and the installed Windows copy; *Actions › Publish* merges and releases.

**Brand (v0.55, v0.57)** — new logo, icons for every system, README banner, accent colour; a bigger mark in the header and on the start pages.

## Next

1. **One feed per login site instead of one read per account** — X's following timeline, pixiv's `follow_latest`, Patreon's stream,
   the Mastodon / Misskey home timeline, a forum's news feed — filling a metadata-only timeline so *All artists* opens without
   asking every site. First measure with a real login whether a feed shows every post of every followed account.
2. **Recommended view** — suggestions per login (X, Bluesky, Mastodon, pixiv, Fanbox, Patreon), each to follow, make a card of, or dismiss.
3. **Limits, tuned by the request tally** — a daily backfill quota, Refresh all in the order of the oldest read, follow lists weekly.
4. **Standalone builds** — in-app update for macOS, the AppImage and portable copies; first runs on real desktops; signing and notarising.
5. **Forums behind a Cloudflare challenge without a login** (through the login window's browser engine).
6. **Mastodon:** an artist on a server you have no account on, read through your own server.
7. **A licence for Sourcerer** (gallery-dl stays a separate process until then).
8. **DeviantArt.**
9. **Updater:** first real run on Windows and macOS.
10. **TrackImage hand-over:** where files are passed on and how duplicates are matched.
11. **X:** resume a long first sync where it stopped. **Quiet hours** for logged-in sites. **Gallery:** a filter by date.
12. **A background refresh** of the snapshots of cards nobody opened, so *All artists* is complete without *Refresh all*.
