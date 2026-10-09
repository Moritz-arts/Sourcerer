# Sourcerer — roadmap

The working memory of the project: where it is going, what is decided, what is
next. Update it in the same commit as the work that changes it — tick a box,
add a decision, move an item. Anyone, with or without Claude, should be able to
pick the project up from this file and `CLAUDE.md` alone.

## Goal

A portable Windows app that keeps per-artist media collections in sync across
sites and drops every new file, de-duplicated across sources, into a
TrackImage library.

## Sources

| Site | Status |
|---|---|
| XenForo Media Gallery | not started |
| Mastodon | not started |
| Patreon | not started |
| Bluesky | not started |
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

## Done

- [x] Repository workshop: CLAUDE.md, docs, version workflow

## Next

- [ ] Program skeleton and the Windows launcher
- [ ] Where Sourcerer hands files to TrackImage, and how duplicates are matched
- [ ] First source
