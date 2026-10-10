#!/usr/bin/env python3
"""Write the new version's entry into docs/CHANGELOG.md, from the commits behind it.

"What happened between v0.3 and v0.9" is a question the repository can always
answer -- the commits are right there -- but only if somebody writes it down
while it is still one version's worth of work. So it is written here, by the
same workflow that raises the number: every commit since the previous tag
becomes one line under the new heading.

One line, not a paragraph. The reasoning is in the commit, a click away and
never stale; this file answers the other question, with a list you can read in
ten seconds and paste into a release.

Called as: changelog_entry.py <new-version>   writes the entry, prints its body
           changelog_entry.py --last-subject  prints the last real commit's subject
"""
import pathlib
import re
import subprocess
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "Sourcerer_files" / "docs" / "CHANGELOG.md"

#: Who makes the workflow's own commits. Matched by author, not by subject:
#: the subject is the work's own line with " (v0.4)" added, so a pattern on it
#: either misses those commits or catches somebody's.
_BOT = "github-actions[bot]"

#: What GitHub writes when a button is pressed. `git log --no-merges` drops a
#: real merge commit, but a squash merge is an ordinary commit carrying the same
#: sentence, and that sentence names the button, not the work.
_MERGE = re.compile(r"^Merge (pull request|branch|remote-tracking)\b", re.I)


def _git(*args):
    return subprocess.run(("git",) + args, cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def previous_tag():
    """The last version tag before HEAD, or nothing on the very first run."""
    try:
        return _git("describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD")
    except subprocess.CalledProcessError:
        return ""


def commits_since(tag):
    """Subject and body of every real commit since that tag, oldest first."""
    span = ("%s..HEAD" % tag) if tag else "HEAD"
    # NUL between commits, \x01 between author, subject and body: a message can contain
    # any number of blank lines, so nothing printable can separate them.
    raw = _git("log", span, "--no-merges", "--reverse",
               "--pretty=format:%an%x01%s%x01%b%x00")
    out = []
    for chunk in raw.split("\x00"):
        chunk = chunk.strip()
        if not chunk:
            continue
        author, subject, body = (chunk.split("\x01", 2) + ["", ""])[:3]
        subject = subject.strip()
        if not subject or author == _BOT or _MERGE.match(subject):
            continue
        out.append((subject, body.strip()))
    return out


def entry_body(commits):
    """One line per change: what it was, nothing else."""
    lines, seen = [], set()
    for subject, _body in commits:
        subject = subject.strip().rstrip(".")
        key = subject.lower()
        if not subject or key in seen:
            continue
        seen.add(key)
        lines.append("- %s" % subject)
    if not lines:
        lines = ["- Maintenance."]
    return "\n".join(lines)


def prepend(version, body):
    """Put the entry directly under the file's heading, newest first."""
    heading = "## v%s — %s" % (version, date.today().isoformat())
    CHANGELOG.parent.mkdir(parents=True, exist_ok=True)
    text = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.is_file() else \
        "# Sourcerer — version history\n"
    if ("## v%s " % version) in text or text.rstrip().endswith("## v%s" % version):
        return False                      # already written; nothing to do
    marker = "\n## "
    at = text.find(marker)
    if at < 0:
        new = text.rstrip() + "\n\n" + heading + "\n\n" + body + "\n"
    else:
        new = text[:at + 1] + heading + "\n\n" + body + "\n\n" + text[at + 1:]
    CHANGELOG.write_text(new, encoding="utf-8")
    return True


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: changelog_entry.py <new-version> | --last-subject")
    commits = commits_since(previous_tag())
    if sys.argv[1] == "--last-subject":
        # For the bump commit's name: the last real commit of this version, not
        # GitHub's "Merge pull request #4 from owner/branch", which names the
        # button that was pressed and not the work.
        print(commits[-1][0] if commits else "")
        return
    version = sys.argv[1].lstrip("vV")
    body = entry_body(commits)
    prepend(version, body)
    print(body)


if __name__ == "__main__":
    main()
