# Sourcerer — what changed

Newest first. Each entry is made from the commit subjects when a version is made, so a subject is one short,
plain sentence.

## v0.57 — 2026-10-23

- A bigger Sourcerer mark in the header and on the start pages, and the code review's fixes for stability and speed
- Every download is named for its system: Sourcerer-Windows.exe and Sourcerer-Linux.AppImage

## v0.56 — 2026-10-23

- README rewritten: short, plain, with a download table
- Changelog and roadmap rewritten in short, plain sentences
- Release notes list what is new and link every download
- Real artist names and handles in comments and notes replaced by templates

## v0.55 — 2026-10-23

- Source order lists an artist under every site it is on; All artists still counts each artist once
- Faster forum galleries
- New logo, app icons and brand colour

## v0.54 — 2026-10-23

- XenForo: the members you follow become cards, with their profile pictures
- A new card from a follow list is looked at once, so it is not empty
- The page's settings (view, sort order, picture size, hidden sites) survive restarts and updates

## v0.53 — 2026-10-23

- Sponsor link added

## v0.52 — 2026-10-23

- XenForo: pictures without a time on the list page are dated from their own page
- Merge sources: "Not the same" is red, the buttons sit in two columns

## v0.51 — 2026-10-23

- Merge sources: one pair at a time, no bulk merge
- XenForo: pictures show their title and are dated from the list page

## v0.50 — 2026-10-23

- Opening an artist again within minutes asks no site

## v0.49 — 2026-10-23

- New defaults: 24 parallel downloads, 32 per site, short gaps, no scan at start
- Merge: every suggestion says why, "Not the same" is remembered; Artists shows eight pictures; Images counts what was posted

## v0.48 — 2026-10-23

- Merge sources: finds cards that look like one artist; bios are read for the accounts they name

## v0.47 — 2026-10-23

- Three views: Artists, Gallery and Recommended (coming)

## v0.46 — 2026-10-23

- Fixes: pixiv stills in the gallery, fewer Mastodon requests, waits for a nearly used-up rate limit

## v0.45 — 2026-10-22

- Refresh all, automatic sync and the scan at start skip sources read recently (longer for quiet artists)

## v0.44 — 2026-10-22

- Fixes: Patreon follow lists no longer pause it on a 403; X rests until its rate-limit window reopens

## v0.43 — 2026-10-22

- Requests are counted as made; All artists never asks login sites (it shows saved snapshots, Refresh all reads them)

## v0.42 — 2026-10-22

- Fixes: a cut-off follow list is not marked done; All artists uses at most half of a login site's day; Cancel works

## v0.41 — 2026-10-22

- X follows: clearer messages; site chips show how many accounts answered

## v0.40 — 2026-10-22

- Fix: the window can be moved again
- X follow list reports what X answers

## v0.39 — 2026-10-22

- Follows: every look logs where each account went
- X follows: better diagnostics

## v0.38 — 2026-10-21

- Speed: faster library lookups, no waiting for every login check at start, saving no longer blocks requests
- X follow lists are retried within hours
- An artist's own gallery goes before All artists in the queue

## v0.37 — 2026-10-20

- All artists: every card, a one-week window with "Load older posts"
- Sites are named and iconed by themselves; a log viewer
- XenForo: cards are named by their member, with profile picture and picture details

## v0.36 — 2026-10-20

- Patreon: opening a followed creator works again

## v0.35 — 2026-10-20

- Browse: site chips no longer overlap, groups fold, no warning dialogs
- X and Patreon follows

## v0.34 — 2026-10-20

- Refresh all scans every artist in list order; half of a login site's day is kept for downloads
- Cards are named by @name; accounts of one name on several sites are combined

## v0.33 — 2026-10-19

- Sourcerer stores no pictures of its own; three artists sync at once on different sites
- Download progress rings, original file names, pixiv animations play
- The activity log links to a failed file; the same artist is found by declared profile links

## v0.32 — 2026-10-19

- Browse: Auto-download switch, right-click download and copy, favorites
- Viewer: zoom, bar on top; Settings: master password and reset
- XenForo forums in a folder or behind an index.php? guard work; Misskey login; Fanbox and Fantia
- The same artist on several sites lands on one card

## v0.31 — 2026-10-18

- Browse: order by source, with each site's logo
- Merge suggests likely twins
- Misskey as a source

## v0.30 — 2026-10-18

- The accounts a login follows join the list as cards (nothing is downloaded); cards can be merged

## v0.29 — 2026-10-18

- The Install button shows at once for a newer release

## v0.28 — 2026-10-18

- Linux: the app window comes from Qt

## v0.27 — 2026-10-18

- Windows update waits for the program to close and reports failures

## v0.26 — 2026-10-18

- Updates: clearer states, Install starts at once; a failed Windows update restarts the old version

## v0.25 — 2026-10-17

- Manage Accounts opens ready to add; XenForo cookies.txt import

## v0.24 — 2026-10-17

- Release fix: the standalone files are attached even when nothing was merged

## v0.23 — 2026-10-17

- Windows and the Linux portable are one file, with Userdata beside it

## v0.22 — 2026-10-17

- Cleaner updates (nothing stale is left), fewer files in the Windows build, English-only installer

## v0.21 — 2026-10-17

- Releases hold only the Stable version; Beta is the main branch

## v0.20 — 2026-10-17

- Merge and release on command (Publish workflow)

## v0.19 — 2026-10-17

- Downloads without Python: Setup.exe, .dmg, .AppImage, portable zips

## v0.18 — 2026-10-16

- Windows standalone build

## v0.17 — 2026-10-16

- Browse: artist picture in the head; X reads faster while a gallery is open

## v0.16 — 2026-10-16

- Browse is the only view: logo-only tiles, green downloaded mark, auto-download cloud, working shortcuts

## v0.15 — 2026-10-16

- Browse: Add artist, list order and counter, right-click delete, faster pictures

## v0.14 — 2026-10-16

- Refresh only looks, Download downloads; Auto-download switch
- Browse opens at once from saved snapshots; Squares / Full layout

## v0.13 — 2026-10-16

- Browse: artists left, posts right, with a site filter
- Add account; faster gallery

## v0.12 — 2026-10-15

- Manage Accounts: a button opens the folder where logins are kept

## v0.11 — 2026-10-15

- Manage Accounts: one row per login with a status dot

## v0.10 — 2026-10-15

- Fixes: gallery deadlock with two X accounts; pixiv keeps unfinished works

## v0.9 — 2026-10-15

- Manage Accounts: a box per login; the card dialog lists only logged-in sites

## v0.8 — 2026-10-12

- A gallery per card; protection for logged-in accounts

## v0.7 — 2026-10-11

- Updates keep your data; logins for every site; boorus; Mastodon and forum fixes

## v0.6 — 2026-10-11

- Pixiv, Patreon, X and XenForo; files already there are not downloaded again

## v0.5 — 2026-10-11

- The console closes once Sourcerer runs; a field per site in the card dialog; logins

## v0.4 — 2026-10-10

- English interface, settings, in-app updates, live link checks

## v0.3 — 2026-10-10

- Window with artist cards; Mastodon and Bluesky downloads

## v0.2 — 2026-10-10

- Launchers for every system; releases with Sourcerer.zip

## v0.1 — 2026-10-09

- First version
