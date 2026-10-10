#!/bin/bash
# Finds a Python 3.10+ and hands over to Sourcerer_files/launch.py, which does
# everything else. Plain POSIX sh on purpose: started as `sh start-linux.sh`,
# dash misreads bash-only syntax and reported a Python that was there as missing.
SELF=$0
# Started through a symlink (a shortcut in ~/bin), Sourcerer_files is beside
# the script, not beside the link.
while [ -L "$SELF" ]; do
    L=$(readlink "$SELF")
    case $L in /*) SELF=$L ;; *) SELF=$(dirname "$SELF")/$L ;; esac
done
SDIR="$(cd "$(dirname "$SELF")" && pwd)/Sourcerer_files"
if [ ! -f "$SDIR/launch.py" ]; then
    echo "  [ERROR] Sourcerer_files/launch.py not found next to this launcher."
    echo "          Unpack the whole archive, keeping start-linux.sh and the"
    echo "          Sourcerer_files folder side by side."
    exit 1
fi
# Each candidate must be 3.10 or newer, not merely present: an old python3
# must not hide a python3.12 installed beside it.
for P in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$P" >/dev/null 2>&1 &&
       "$P" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        exec "$P" "$SDIR/launch.py" "$@"
    fi
done
echo "  [ERROR] Sourcerer needs Python 3.10 or newer, and none was found."
echo "          Debian/Ubuntu: sudo apt install python3 python3-venv"
echo "          Fedora:        sudo dnf install python3"
exit 1
