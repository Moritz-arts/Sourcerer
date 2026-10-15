# Sourcerer — version history

Every push to `main` raises the version by one and adds its entry here
automatically -- one line per change, newest first. A release is drafted by hand
from the tag of whichever version is judged ready, and this is the text to paste
into it.

## v0.10 — 2026-10-15

- Review fixes: the gallery no longer deadlocks on two X accounts, pixiv keeps unfinished works, a blocked artist no longer pauses X (#10)

## v0.9 — 2026-10-15

- Manage Accounts: a box per login with a status dot beside Sync all, and the card dialog lists only logged-in sites (#9)

## v0.8 — 2026-10-12

- A gallery per card shows all its sources at once, and logged-in accounts are protected from looking like a bot

## v0.7 — 2026-10-11

- Updates leave Userdata and venv where they are, log every step at once, and report a failed update on the next start
- Logins for every site, boorus as a source, and Mastodon servers and forums with a bot check work again
- Logins and boorus hold up under review: no lasting TLS downgrade, foreign pages refused, dead logins read as a visitor

## v0.6 — 2026-10-11

- Pixiv, Patreon, X and XenForo forums are downloaded; files already there are not downloaded again; a warning when a login runs out

## v0.5 — 2026-10-11

- The console closes once Sourcerer is up; the card dialog has a field per site; logins under Settings > Accounts

## v0.4 — 2026-10-10

- English interface with settings, in-app updates, live link checks and faster, gentler downloads

## v0.3 — 2026-10-10

- Every new version is downloadable as Sourcerer.zip from the beta prerelease
- Sourcerer opens a window with artist cards and downloads from Mastodon and Bluesky
- Window and card dialog follow the design mockups; same picture across sources kept once

## v0.2 — 2026-10-10

- Launchers only find Python; launch.py sets up and starts Sourcerer on all systems
- Releases get Sourcerer.zip, which unpacks to a single Sourcerer folder

## v0.1 — 2026-10-09

- Initial commit
- Repository workshop as in TrackImage: version workflow, CLAUDE.md, docs
- Launchers for Windows, Linux and macOS; all machine state inside Sourcerer_files
