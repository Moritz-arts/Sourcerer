"""Prepare Sourcerer's Python environment and start app.py.

The three launchers in the root only find a Python 3.10+ and hand over to this
file. Everything after that -- the environment, the packages, the start -- is
written once, here, instead of three times in three shell languages that drift
apart. Standard library only: it runs before any package is installed.
"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REQS = HERE / "requirements.txt"
SYSTEM = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
# One environment per system. The folder is portable, and one venv shared by
# Windows and Linux -- a USB stick, a dual boot -- is one neither can run.
VENV = HERE / "venv" / SYSTEM
STAMP = VENV / "requirements.installed"
# pip caches in the user's home by default; kept here instead, nothing is
# written outside the folder Sourcerer was unpacked into.
PIP_CACHE = HERE / "venv" / "pip-cache"


def say(text=""):
    print("  " + text if text else "", flush=True)


def venv_python():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def healthy():
    """True when the environment runs and has pip -- not merely when its python exists.

    An interrupted first start leaves python behind without pip, and after a
    Python upgrade or uninstall the venv points at an interpreter that is gone
    or looks in a site-packages that does not exist. A file check took all of
    these for a finished environment, every start after, for good.
    """
    py = venv_python()
    if not py.is_file():
        return False
    try:
        return subprocess.run([str(py), "-c", "import pip"], capture_output=True,
                              timeout=120).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def wanted():
    """What the stamp must say: these requirements, on this interpreter."""
    digest = hashlib.sha256(REQS.read_bytes()).hexdigest()
    return "%s %d.%d" % (digest, sys.version_info[0], sys.version_info[1])


def create():
    say("[1/3] Creating the Python environment...")
    # --clear: what is there is broken (healthy() said so); building over it
    # trips on dangling links to an interpreter that is gone.
    rc = subprocess.call([sys.executable, "-m", "venv", "--clear", str(VENV)])
    if rc == 0 and healthy():
        return True
    shutil.rmtree(VENV, ignore_errors=True)
    say("[ERROR] Could not create the Python environment, see above.")
    return False


def install():
    say("[2/3] Installing packages...")
    env = dict(os.environ, PIP_CACHE_DIR=str(PIP_CACHE),
               PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONNOUSERSITE="1")
    rc = subprocess.call([str(venv_python()), "-m", "pip", "install", "-q",
                          "-r", str(REQS)], env=env)
    # Any non-zero code, negative ones included: a crash or Ctrl+Break must not
    # leave a stamp behind that skips the install on every start after.
    if rc != 0:
        say("[ERROR] Installing packages failed, see above.")
        return False
    STAMP.write_text(wanted(), encoding="utf-8")
    return True


def main():
    os.chdir(HERE)
    version = (HERE / "VERSION").read_text(encoding="utf-8").strip()
    say()
    say("========================================")
    say(" Sourcerer v%s - Setup & Start" % version)
    say("========================================")
    say()
    if not healthy() and not create():
        return 1
    try:
        current = STAMP.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if current != wanted() and not install():
        return 1
    say("[3/3] Starting Sourcerer...")
    say()
    env = dict(os.environ, PYTHONNOUSERSITE="1")
    args = [str(venv_python()), str(HERE / "app.py")] + sys.argv[1:]
    if os.name == "nt":
        return subprocess.call(args, env=env)
    os.execve(args[0], args, env)   # app.py takes over this process and its exit code


if __name__ == "__main__":
    sys.exit(main())
