#!/usr/bin/env python3
"""The text of a release: what is new (the version's section of docs/CHANGELOG.md), then what to download.

Called as: release_notes.py <tag> [changelog-file]
The changelog defaults to the one in the working tree. A tag whose section is missing gets the download table alone.
Used by publish.yml when a release is made and by release-notes.yml to rewrite the notes of releases already out:
there the environment variable ASSETS names the files the release holds, so a release from before the files were
renamed links its own names and leaves out what it never had.
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "Sourcerer_files" / "docs" / "CHANGELOG.md"
REPO = os.environ.get("GITHUB_REPOSITORY", "Moritz-arts/Sourcerer")

#: (system, [(label, file, name before v0.57 or "")]) -- the files build-exe.yml and release-zip.yml attach.
DOWNLOADS = [
    ("Windows", [("installer", "Sourcerer-Windows.exe", "Sourcerer-Setup.exe"), ("portable", "Sourcerer-Windows.zip", "")]),
    ("macOS", [("Apple silicon", "Sourcerer-macOS-arm64.dmg", ""), ("Intel", "Sourcerer-macOS-x86_64.dmg", "")]),
    ("Linux", [("AppImage", "Sourcerer-Linux.AppImage", "Sourcerer-x86_64.AppImage"),
               ("portable, browser only", "Sourcerer-Linux.tar.gz", "")]),
    ("With Python 3.10+", [("any system, updates itself", "Sourcerer.zip", "")]),
]


def section(text, tag):
    """The bullet lines under '## <tag> -- <date>', up to the next version."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.startswith("## %s " % tag) or line.strip() == "## %s" % tag
            continue
        if inside and line.strip():
            out.append(line.rstrip())
    return out


def table(tag, assets):
    """The download rows. `assets` is the names a release already holds (an old one has its old names, some none at
    all); None while a release is being made: its files come minutes later, under today's names."""
    base = "https://github.com/%s/releases/download/%s/" % (REPO, tag)
    rows = []
    for system, files in DOWNLOADS:
        links = []
        for label, name, old in files:
            name = name if assets is None or name in assets else old if old in assets else ""
            if name:
                links.append("[%s](%s%s) (%s)" % (name, base, name, label))
        if links:
            rows.append("| **%s** | %s |" % (system, " · ".join(links)))
    return ["### Download", "", "| System | Files |", "|---|---|"] + rows + [
        "",
        "The files are not signed: the first start shows a warning once (see the [README](https://github.com/%s#download))." % REPO,
    ] if rows else []


def notes(tag, text, assets=None):
    lines = section(text, tag)
    return "\n".join((["### What's new", ""] + lines + [""] if lines else []) + table(tag, assets)) + "\n"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: release_notes.py <tag> [changelog-file]")
    tag = "v" + sys.argv[1].lstrip("vV")
    path = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else CHANGELOG
    assets = os.environ.get("ASSETS")      # the release's file names, one per line (release-notes.yml)
    sys.stdout.write(notes(tag, path.read_text(encoding="utf-8") if path.is_file() else "",
                           None if assets is None else assets.split()))


if __name__ == "__main__":
    main()
