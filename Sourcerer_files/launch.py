"""Prepare Sourcerer's Python environment and start app.py.

The three launchers in the root only find a Python 3.10+ and hand over to this
file. Everything after that -- the environment, the packages, the start -- is
written once, here, instead of three times in three shell languages that drift
apart. Standard library only: it runs before any package is installed.
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
REQS = HERE / "requirements.txt"
APP = HERE / "app.py"
RUNNING = HERE / "Userdata" / "running.json"      # written by Sourcerer once it serves
CONSOLE_LOG = HERE / "Userdata" / "Logs" / "console.log"
SYSTEM = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
# One environment per system. The folder is portable, and one venv shared by
# Windows and Linux -- a USB stick, a dual boot -- is one neither can run.
VENV = HERE / "venv" / SYSTEM
STAMP = VENV / "requirements.installed"
# pip caches in the user's home by default; kept here instead, nothing is
# written outside the folder Sourcerer was unpacked into.
PIP_CACHE = HERE / "venv" / "pip-cache"
# Left by Settings > Repair: the environment is thrown away and built anew.
REBUILD = HERE / "Userdata" / "rebuild-venv"


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


def requirements():
    """(required, optional) package specs from requirements.txt."""
    required, optional = [], []
    for line in REQS.read_text(encoding="utf-8").splitlines():
        spec = line.split("#", 1)[0].strip()
        if spec:
            (optional if "# optional" in line else required).append(spec)
    return required, optional


def install():
    say("[2/3] Installing packages...")
    env = dict(os.environ, PIP_CACHE_DIR=str(PIP_CACHE),
               PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONNOUSERSITE="1")
    pip = [str(venv_python()), "-m", "pip", "install", "-q"]
    required, optional = requirements()
    # Any non-zero code, negative ones included: a crash or Ctrl+Break must not
    # leave a stamp behind that skips the install on every start after.
    if required and subprocess.call(pip + required, env=env) != 0:
        say("[ERROR] Installing packages failed, see above.")
        return False
    # The window package needs things pip cannot always provide (a GUI toolkit
    # on Linux, a .NET bridge on a brand-new Python); without it Sourcerer
    # opens in the browser, which is no reason to refuse to start at all.
    for spec in optional:
        if subprocess.call(pip + [spec], env=env) != 0:
            say("[note] %s did not install; Sourcerer works without it." % spec)
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
    if REBUILD.exists():
        say("Rebuilding the Python environment, as asked in Settings...")
        for _ in range(20):            # Windows: the old interpreter may still be closing
            shutil.rmtree(VENV, ignore_errors=True)
            if not VENV.exists():
                break
            time.sleep(0.5)
        REBUILD.unlink(missing_ok=True)
    if not healthy() and not create():
        return 1
    try:
        current = STAMP.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if current != wanted() and not install():
        return 1
    if already_running():
        return 0
    say("[3/3] Starting Sourcerer...")
    env = dict(os.environ, PYTHONNOUSERSITE="1")
    args = [a for a in sys.argv[1:] if a != "--console"]
    if "--console" in sys.argv[1:]:     # stay attached: every message on screen, for debugging
        say()
        cmd = [str(venv_python()), str(APP)] + args
        if os.name == "nt":
            return subprocess.call(cmd, env=env)
        os.execve(cmd[0], cmd, env)
    return start(args, env)


def _local(path, data=None):
    """A request to a Sourcerer on this machine -- never through a proxy."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request("http://127.0.0.1:%s" % path, data=data), timeout=2) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _running(since=0.0):
    """What the running Sourcerer wrote about itself, if it still answers."""
    try:
        info = json.loads(RUNNING.read_text(encoding="utf-8"))
        if info.get("started", 0) >= since and \
                _local("%s/api/ping" % info["port"]).get("app") == "sourcerer":
            return info
    except (OSError, ValueError, KeyError):
        pass
    return None


def already_running():
    """One Sourcerer at a time: a second start brings the first one forward."""
    info = _running()
    if not info:
        return False
    try:
        _local("%s/api/focus" % info["port"], data=b"")
    except (OSError, ValueError):
        pass
    say("Sourcerer is already running -- switched to it.")
    return True


def start(args, env):
    """Start Sourcerer on its own and return as soon as it answers, so the console can close.

    TrackImage's way: the console is there for the setup -- a first start
    installs packages for minutes and has to show that it is working -- not
    for the running program. On Windows pythonw.exe has no console at all;
    elsewhere the program leaves the terminal's session. What it prints goes
    to Userdata/Logs/console.log, which is shown here when the start fails.
    """
    pyw = VENV / "Scripts" / "pythonw.exe"
    py = pyw if os.name == "nt" and pyw.is_file() else venv_python()
    CONSOLE_LOG.parent.mkdir(parents=True, exist_ok=True)
    since = time.time() - 1
    with open(CONSOLE_LOG, "w", encoding="utf-8") as out:
        kwargs = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT,
                  "env": dict(env, SOURCERER_DETACHED="1"), "cwd": str(HERE)}
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000008 | 0x00000200   # detached, own process group
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([str(py), str(APP)] + args, **kwargs)
    say("Waiting for Sourcerer to answer...")
    deadline = time.time() + 120
    while time.time() < deadline:
        info = _running(since)
        if info:
            say("Sourcerer is running at http://127.0.0.1:%s/" % info["port"])
            if os.name != "nt":
                say("This window is no longer needed.")
            return 0
        if proc.poll() is not None:
            break
        time.sleep(0.3)
    say()
    say("[ERROR] Sourcerer did not start. Its last words:")
    say()
    try:
        for line in CONSOLE_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]:
            say(line)
    except OSError:
        pass
    say()
    say("Start it with --console to watch it start, or see Userdata/Logs.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
