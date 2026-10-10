# Sourcerer — roadmap

The working memory of the project: where it is going, what is decided, what is
next. Update it in the same commit as the work that changes it — tick a box,
add a decision, move an item. Anyone, with or without Claude, should be able to
pick the project up from this file and `CLAUDE.md` alone.

## Goal

A portable app for Windows, Linux and macOS that keeps per-artist media
collections in sync across sites and drops every new file, de-duplicated across
sources, into a TrackImage library.

## Sources

| Site | Status |
|---|---|
| XenForo Media Gallery | not started |
| Mastodon (and the fediverse) | **works** — public posts, originals |
| Patreon | not started |
| Bluesky | **works** — public posts, original blobs incl. video |
| X | not started |
| Pixiv | not started |
| DeviantArt | not started |

## Decisions

Record each as: date — decision — why. Never delete one; strike it through and
add the one that replaced it.

- 2026-10-09 — Same workshop as TrackImage: version raised and changelog
  written by a workflow on every push to `main`, workshop files kept out of
  the archive. — One way of working across both projects.
- 2026-10-09 — The version lives in `Sourcerer_files/VERSION`, a plain file,
  not in code. — No code exists yet, and a plain file is the easiest thing for
  both the program and the updater to read.
- 2026-10-09 — Windows, Linux and macOS, each with a launcher in the root
  (`start-windows.bat`, `start-linux.sh`, `start-macos.command`). — Same
  reach as TrackImage.
- 2026-10-09 — The system Python (3.10+) and a `venv` inside `Sourcerer_files/`,
  as in TrackImage, instead of a bundled runtime; packages come from one
  `requirements.txt`. — One setup path for all three systems; the root stays
  clean because all machine state lives in `Sourcerer_files/`.
- 2026-10-10 — The launchers only find a Python 3.10+; `Sourcerer_files/launch.py`
  does everything after that (environment, packages, start). — One
  implementation instead of three shell languages, and testable on any system.
- 2026-10-10 — One venv per system (`venv/windows|linux|macos`), checked by
  running it; pip's cache inside `venv/`. — The folder is portable; a venv
  built by one system cannot run on another, and a broken one must heal itself.
- 2026-10-10 — The notes for Claude live in `.claude/CLAUDE.md`, not in the
  root. — The root holds only what a user needs to start Sourcerer.
- 2026-10-10 — Every published release gets `Sourcerer.zip`, with the
  launchers at its top, built by a workflow. — GitHub's own archive wraps
  everything in `Sourcerer-<ref>/`, so unpacking it gave two folder levels;
  Sourcerer.zip unpacks to exactly one, `Sourcerer/`.
- 2026-10-10 — The program is built like TrackImage: Flask on 127.0.0.1, a
  pywebview window (the browser when that cannot open), vanilla JS, SQLite in
  `Userdata/`. — Same stack, same habits, one person maintaining both.
- 2026-10-10 — Downloads go to `<library>/<artist>/<date>_<site>_<id>.<ext>`;
  a file is new when its remote key was never seen for the artist, and kept
  unless the same bytes are already there. — Sorted by date in any file
  manager; deleted files are not brought back; near-duplicates are left to
  TrackImage, which already finds them.
- 2026-10-10 — HTTP with the standard library, no requests. — Two calls do not
  justify a dependency on three systems.
- 2026-10-10 — Every new version also replaces Sourcerer.zip on the prerelease
  `beta`. — A clean download of the newest build without publishing a release
  by hand; Stable stays what was published deliberately.

## Done

- [x] Repository workshop: CLAUDE.md, docs, version workflow
- [x] Launchers for Windows, Linux and macOS; `app.py` placeholder
- [x] Audit: launchers, version workflow and docs checked and corrected
- [x] Program skeleton: window, artist cards (name, notes, source links),
      settings (library folder), background sync with status and log
- [x] First sources: Mastodon and Bluesky

## Next

- [ ] Updater in the program, with a switch between two channels:
      **Stable** — the newest GitHub release (its Sourcerer.zip);
      **Beta** — the newest build of `main` (Sourcerer.zip on the `beta`
      prerelease). Same rules as TrackImage's updater: verify the
      archive, carry `Userdata/` and `venv/` across, keep the folder's name.
- [ ] Where Sourcerer hands files to TrackImage, and how duplicates are matched
- [ ] Next sources: DeviantArt, Pixiv, X, Patreon, XenForo (most need a login
      or cookies -- stored in `Userdata/`, never logged)
- [ ] Scheduled sync (every N hours while the window is open)
