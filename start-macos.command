#!/bin/bash
# .command so Finder starts it on a double-click -- in $HOME, which is why the
# path below is built from the script's own location, never the current folder.
# Everything Sourcerer owns lives one level down, in Sourcerer_files. This
# launcher is the only thing in the unpacked folder, so it steps in there itself.
SDIR="$(cd "$(dirname "$0")" && pwd)/Sourcerer_files"
if [ ! -f "$SDIR/app.py" ]; then
    echo "  [ERROR] Sourcerer_files/app.py not found next to this launcher."
    echo "          Unpack the whole archive, keeping start-macos.command and the"
    echo "          Sourcerer_files folder side by side."
    exit 1
fi
cd "$SDIR" || exit 1
echo ""
echo "  ========================================"
echo "   Sourcerer v0.1 - Setup & Start (macOS)"
echo "  ========================================"
echo ""

if ! command -v python3 &> /dev/null; then
    echo "  [ERROR] Python 3 not found. Install it with Homebrew: brew install python"
    echo "          or from https://www.python.org/downloads/macos/"
    exit 1
fi
# Older ones get through the setup and fail later on syntax, which reads like a
# broken download rather than an old interpreter.
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "  [ERROR] $(python3 --version) is too old or missing. Sourcerer needs 3.10+:"
    echo "          brew install python, or https://www.python.org/downloads/macos/"
    exit 1
fi

# venv/bin/python, not the folder: Debian without python3-venv leaves a
# half-made venv behind, and a folder check would take that for a finished one.
if [ ! -x venv/bin/python ]; then
    echo "  [1/3] Creating the Python environment..."
    if ! python3 -m venv venv; then
        rm -rf venv
        echo "  [ERROR] Could not create it, see above."
        exit 1
    fi
fi
# Everything Sourcerer needs lives in THIS venv; per-user packages stay out.
export PYTHONNOUSERSITE=1

# Only when requirements.txt changed -- pip on every start costs seconds for nothing.
if ! cmp -s requirements.txt venv/requirements.installed; then
    echo "  [2/3] Installing dependencies..."
    venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt \
        || { echo "  [ERROR] Installing dependencies failed, see above."; exit 1; }
    cp requirements.txt venv/requirements.installed
fi

echo "  [3/3] Starting Sourcerer..."
echo ""
exec venv/bin/python app.py "$@"
