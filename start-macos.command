#!/bin/bash
# .command so Finder starts it on a double-click -- in $HOME, which is why the
# folder comes from the script's own location, never from the current one.
# Finds a Python 3.10+ and hands over to Sourcerer_files/launch.py, which does
# everything else.
SELF=$0
# Started through a symlink, Sourcerer_files is beside the script, not the link.
while [ -L "$SELF" ]; do
    L=$(readlink "$SELF")
    case $L in /*) SELF=$L ;; *) SELF=$(dirname "$SELF")/$L ;; esac
done
SDIR="$(cd "$(dirname "$SELF")" && pwd)/Sourcerer_files"
if [ ! -f "$SDIR/launch.py" ]; then
    echo "  [ERROR] Sourcerer_files/launch.py not found next to this launcher."
    echo "          Unpack the whole archive, keeping start-macos.command and the"
    echo "          Sourcerer_files folder side by side."
    exit 1
fi
# /usr/bin/python3 is only Apple's stub until the Command Line Tools are
# installed: running it asks to install them and fails, so it is skipped then.
# Homebrew's and python.org's interpreters are also looked for by path, in case
# the PATH a Finder start gets does not include them.
for P in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
    P=$(command -v "$P" 2>/dev/null) || continue
    if [ "$P" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; then
        continue
    fi
    if "$P" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        exec "$P" "$SDIR/launch.py" "$@"
    fi
done
echo "  [ERROR] Sourcerer needs Python 3.10 or newer, and none was found."
echo "          Install it from https://www.python.org/downloads/macos/"
echo "          or with Homebrew: brew install python"
exit 1
