# Sourcerer — version history

Every push to `main` raises the version by one and adds its entry here
automatically -- one line per change, newest first. A release is drafted by hand
from the tag of whichever version is judged ready, and this is the text to paste
into it.

## v0.33 — 2026-10-19

- Sourcerer keeps no pictures and syncs three artists at once on different sites; order and number lists cleaned up, download rings, file names, ugoira plays, taskbar stays, more follows
- The activity log jumps to a failed file's picture or post; the same artist is found by declared profile links and account names, not display names alone
- A picture in the library wears the download button in green, however it got there, and loses it when its file is deleted

## v0.32 — 2026-10-19

- Browse: no Download all button, an Auto-download switch beside Download, only green clouds in the list, a bigger artist head, right-click to download or copy a picture, red close buttons
- XenForo: forums in a folder or behind an index.php? guard log in, keep their login across redirects and list their media
- Follows: the same artist's accounts on different sites land on one card by themselves, and cards that are already apart are combined
- Viewer: the bar moves to the top, a click on the dark closes it, double-click and wheel zoom, a switch in Appearance hides the site mark on the pictures
- Settings: more parallel downloads and connections per site, a master password asked at every start, a reset to a fresh install, and a TrackImage card
- Browse: download one picture, several or the whole artist, GIFs play, more orders and numbers, latest activity by the newest post, a scan at every start, the window's own title bar
- Refresh checks one artist at a time, the opened artist first, and only auto-download cards; Misskey login, Fanbox and Fantia, sharper grid pictures, favorites

## v0.31 — 2026-10-18

- Browse: a third order, by source, with each site's logo and a line above its artists
- Merge: likely twins (names that differ only by emoji, marks or case) are suggested at the top, several cards are ticked and merged with one button, no extra confirmation
- Misskey: accounts on misskey.io and other Misskey servers (also those a Baraag follow list names) are a source of their own

## v0.30 — 2026-10-18

- Follows: the accounts a login follows join the list as artists, nothing downloaded; artists can be merged
- Follows hardened: only public https links and pictures, Host checked on reads, lists end where the site says, merge keeps its files

## v0.29 — 2026-10-18

- Updates: the Install button shows at once for a newer release, greyed until its file is attached

## v0.28 — 2026-10-18

- Linux: the app window comes from Qt (PyQt6 from pip) in the launcher and the AppImage

## v0.27 — 2026-10-18

- Updates: a release that lacks this system's file links to its release page
- Windows update: Setup waits for Sourcerer.exe to be free and never forces it closed, and the update helper reports a failed Setup or a helper that did not start

## v0.26 — 2026-10-18

- Updates: a release whose files are still being attached is reported as such, not as up to date
- Updates: Install starts the update at once, without a confirmation question
- Windows update: Setup starts only once Sourcerer has exited, logs to setup.log, and the old program restarts when Setup fails

## v0.25 — 2026-10-17

- Manage Accounts opens with the add row ready; a forum's login window is logged and XenForo offers cookies.txt import in the app window

## v0.24 — 2026-10-17

- Publish: the job that attaches the standalone files runs even when no branch was merged

## v0.23 — 2026-10-17

- Windows and the Linux portable are one file, like Pikura's: Sourcerer.exe with Userdata beside it

## v0.22 — 2026-10-17

- The old beta tag is deleted even when its release was already gone
- An update installs cleanly and removes what is gone; the Windows build has fewer files; the installer is English only
- The smoke test expects an installed Windows copy to update itself, and prints the bundle's top-level count

## v0.21 — 2026-10-17

- Releases hold only the Stable version, Beta is the main branch; the README download table is compact like Pikura's

## v0.20 — 2026-10-17

- Publish workflow: merge a branch into main and release it as Stable on command; README downloads link to the latest release

## v0.19 — 2026-10-17

- Downloads without Python for Windows, macOS and Linux: Sourcerer-Setup.exe, .dmg, .AppImage and portable zips

## v0.18 — 2026-10-16

- Windows: Sourcerer.exe, a standalone build with Python inside, as Sourcerer-Windows.zip

## v0.17 — 2026-10-16

- Browse: the artist's picture beside the title, the artist's name beside the site mark in All artists, X reads faster while an artist's gallery is open

## v0.16 — 2026-10-16

- Browse is the only view: logo-only tiles, green downloaded mark, always-visible auto-download cloud, site logos in accounts and viewer, working shortcuts, galleries kept aside so switching asks no site

## v0.15 — 2026-10-16

- Browse: add-artist button, order and counter for the list, right-click delete, site logos instead of names, a spinner that circles, the large view fills the window, sharper tiles, pictures load faster

## v0.14 — 2026-10-16

- Sync only looks and Download downloads, cards get an Auto-download switch and four buttons, Browse opens at once from kept snapshots with spinner and green chips, and the grid can show squares or whole pictures
- Review fixes: the count of posts waiting for a download is kept per source, a download is never widened or lost in the queue, snapshots cannot run code, Browse checks every seeded site, a deferred card look comes back
- Review fixes: Full mode learns the real shape of pictures and no longer flickers, spinners end, cards are patched instead of rebuilt, Ctrl+Shift+R is not Download all
- Review fixes, round 2: a download is never lost in the queue, Browse counts new posts by the first post it knows, every unchecked source gets its check, snapshot tails expire

## v0.13 — 2026-10-16

- Manage your accounts: Add account button, a faster gallery, and cards that show the 4 newest posts
- Review fixes: closing a gallery no longer spins, a login being made shows its row, previews respect login sites
- Browse: the artists you follow on the left, their posts from every source on the right, with a site filter and Download all
- Browse review fixes: queued fills of a closed gallery do not run, every X/forum/login source gets its turn, the page copes with empty and changing states

## v0.12 — 2026-10-15

- Manage Accounts: a Login files button opens the folder where the logins are kept

## v0.11 — 2026-10-15

- Manage Accounts: one row per login, one under the other, with a green, orange or red dot

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
