"""Sourcerer's entry point. The launchers start this file and nothing else.

The program itself does not exist yet; this only proves the launchers work on
all three systems and shows which version is installed.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
# The one place the version is defined -- the workflow raises it on every push.
VERSION = (HERE / "VERSION").read_text(encoding="utf-8").strip()


def main():
    print("  Sourcerer v%s  (Python %s)" % (VERSION, sys.version.split()[0]))
    print("  Nothing to do yet -- the program itself is still being built.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
