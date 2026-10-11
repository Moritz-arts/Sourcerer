"""Updates and repairs: Sourcerer.zip from GitHub, swapped in by a helper.

Two channels, chosen in Settings:

    stable   the newest published release and its Sourcerer.zip
    beta     the newest build of main: Sourcerer.zip on the 'beta' prerelease

A new version cannot be put in place while Sourcerer runs -- on Windows a
running program locks its folder, and the venv's python.exe lives inside it.
So the archive is downloaded, checked and unpacked while Sourcerer runs (into
Userdata/_update, which travels with Userdata), and HELPER -- written to the
system temp folder and started with the system's Python, never the venv's --
waits for Sourcerer to exit, moves the old Sourcerer_files aside, puts the new
one in place, carries Userdata/ and venv/ across, replaces the launchers, and
starts Sourcerer again. When anything fails it puts the old version back. Every
step goes to Userdata/Logs/update.log, which the next start shows.
"""
import logging
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import requests

from . import config, net

log = logging.getLogger(__name__)
API = "https://api.github.com/repos/%s" % config.REPO
STAGE_REL = "Userdata/_update/new"             # relative to Sourcerer_files
REQUIRED = ("Sourcerer_files/VERSION", "Sourcerer_files/launch.py",
            "Sourcerer_files/app.py", "start-windows.bat")


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def check(channel):
    """What the channel offers: {"version", "available", "url", "notes", "page"}."""
    try:
        rel = net.get_json(API + ("/releases/tags/beta" if channel == "beta" else "/releases/latest"))
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 404:
            raise
        rel = {}                                   # nothing published on this channel yet
    if channel == "beta":
        m = re.search(r"\(v([\d.]+)\)", rel.get("name") or "")
        version = m.group(1) if m else ""
    else:
        version = (rel.get("tag_name") or "").lstrip("vV")
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == "Sourcerer.zip"), None)
    return {"channel": channel, "current": config.VERSION, "version": version,
            "available": bool(asset and version_tuple(version) > version_tuple(config.VERSION)),
            "url": asset["browser_download_url"] if asset else "",
            "notes": rel.get("body") or "", "page": rel.get("html_url") or ""}


def install(channel):
    info = check(channel)
    if not info["url"]:
        raise RuntimeError("This channel has no Sourcerer.zip to install.")
    if not info["available"]:
        raise RuntimeError("Sourcerer is up to date.")
    _stage(info["url"], info["version"])
    _launch_helper(swap=True)
    return info


def reinstall():
    """The installed version again, from its tag -- a repair for damaged files."""
    url = "https://codeload.github.com/%s/zip/refs/tags/v%s" % (config.REPO, config.VERSION)
    _stage(url, config.VERSION)
    _launch_helper(swap=True)


def restart():
    """Start Sourcerer again once this one has closed."""
    _launch_helper(swap=False)


def _stage(url, version):
    shutil.rmtree(config.UPDATE_DIR, ignore_errors=True)
    config.UPDATE_DIR.mkdir(parents=True)
    part, _sha, _ext, _name = net.download(url, config.UPDATE_DIR)
    archive = config.UPDATE_DIR / "Sourcerer.zip"
    os.replace(part, archive)
    extract(archive, config.ROOT / STAGE_REL, version)
    log.info("update to v%s staged", version)


def extract(archive, dest, expected=""):
    """Check that archive is Sourcerer (in the expected version) and unpack it into dest.

    GitHub's own archives put everything under one folder (Sourcerer-0.4/);
    Sourcerer.zip does not. Both are accepted.
    """
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        for n in names:
            parts = pathlib.PurePosixPath(n).parts
            if n.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                raise RuntimeError("The archive contains an unsafe path: %s" % n)
        prefix = ""
        if REQUIRED[0] not in names:
            tops = {n.split("/", 1)[0] + "/" for n in names if "/" in n}
            prefix = next((t for t in tops if t + REQUIRED[0] in names), None)
            if prefix is None:
                raise RuntimeError("This archive is not Sourcerer.")
        missing = [r for r in REQUIRED if prefix + r not in names]
        if missing:
            raise RuntimeError("The archive is incomplete: %s missing." % ", ".join(missing))
        found = z.read(prefix + REQUIRED[0]).decode("utf-8").strip()
        if expected and found != expected:
            raise RuntimeError("The archive holds v%s, not v%s." % (found, expected))
        shutil.rmtree(dest, ignore_errors=True)
        for info in z.infolist():
            if not info.filename.startswith(prefix) or info.filename == prefix:
                continue
            target = dest / info.filename[len(prefix):]
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            mode = (info.external_attr >> 16) & 0o777
            if mode and os.name != "nt":
                os.chmod(target, mode)     # the shell launchers stay executable
    return found


def _base_python():
    """The system's Python: the venv's lives in the folder the helper replaces."""
    base = getattr(sys, "_base_executable", "") or ""
    root = pathlib.Path(sys.base_prefix)
    if os.name == "nt":
        for name in ("pythonw.exe", "python.exe"):            # pythonw: no console flashing up
            if (root / name).is_file():
                return str(root / name)
    if base and pathlib.Path(base).is_file() and not str(base).startswith(str(config.ROOT)):
        return base
    for name in ("bin/python3", "bin/python"):
        if (root / name).is_file():
            return str(root / name)
    return sys.executable


def _launch_helper(swap):
    helper = pathlib.Path(tempfile.gettempdir()) / ("sourcerer-helper-%d.py" % os.getpid())
    helper.write_text(HELPER, encoding="utf-8")
    # On Windows the venv's pythonw.exe is a stub that runs the real
    # interpreter as its child and waits for it -- inside Sourcerer_files, so
    # it holds the folder too. launch.py itself left once Sourcerer answered.
    pids = [os.getpid()] + ([os.getppid()] if os.name == "nt" else [])
    args = [_base_python(), str(helper), "--install", str(config.INSTALL),
            "--stage", STAGE_REL if swap else "-", "--pids", ",".join(map(str, pids))]
    kwargs = {"cwd": tempfile.gettempdir(), "stdin": subprocess.DEVNULL,
              "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # detached, own group, no window
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)
    log.info("helper started: %s", " ".join(args))


# The helper runs on its own, from the temp folder, with nothing of Sourcerer
# loaded. Standard library only. It must not sit in the folder it replaces: a
# script whose folder is deleted under it simply stops (TrackImage's lesson).
#
# It swaps the program's own files and folders one by one and never touches
# Userdata/ or venv/. v0.5 renamed Sourcerer_files as a whole, and on Windows
# a rename fails while anything holds a folder inside -- an Explorer window on
# the library (Userdata/Library), a virus scanner: the update never happened,
# and as its log was written only at the very end, nothing said why.
# Every step is written to update.log the moment it happens.
HELPER = r"""
import datetime, os, shutil, subprocess, sys, time, traceback

a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
install, stage_rel = a["--install"], a["--stage"]
pids = [int(p) for p in a["--pids"].split(",") if p]
files = os.path.join(install, "Sourcerer_files")
KEEP = {"Userdata", "venv"}                     # the machine's, never the program's
logdir = os.path.join(files, "Userdata", "Logs")


def say(m):
    line = "%s  %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), m)
    try:
        os.makedirs(logdir, exist_ok=True)
        with open(os.path.join(logdir, "update.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def alive(pid):
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)            # SYNCHRONIZE
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102      # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)                                      # never on Windows: there it kills
        return True
    except OSError:
        return False


def move(src, dst, patience=60):
    # Windows refuses a rename while anything holds the file or folder; a
    # virus scanner lets go after a moment, so try for a while.
    deadline = time.time() + patience
    while True:
        try:
            os.replace(src, dst) if os.path.isfile(src) else os.rename(src, dst)
            return
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(0.5)


def start_again():
    env = dict(os.environ, SOURCERER_AFTER_UPDATE="1")
    if os.name == "nt":
        bat = os.path.join(install, "start-windows.bat")
        try:   # a console of its own: cmd /c closes it when the launcher is done
            subprocess.Popen(["cmd.exe", "/c", bat], cwd=install, env=env,
                             creationflags=0x00000010, close_fds=True)   # CREATE_NEW_CONSOLE
        except OSError:
            os.environ.update(env)
            os.startfile(bat)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", os.path.join(install, "start-macos.command")], env=env)
    else:
        logf = open(os.path.join(logdir, "console.log"), "a")
        subprocess.Popen(["sh", os.path.join(install, "start-linux.sh"), "--no-open"
                          if os.environ.get("SOURCERER_TEST") else "--browser"], env=env,
                         stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                         start_new_session=True, cwd=install)
    say("Sourcerer started again")


def finish(ok):
    say("done" if ok else "update failed, old version kept")    # before the start reads the log
    try:
        start_again()
    except Exception as e:
        say("could not start Sourcerer again: %s -- start it by hand" % e)
    try:
        os.remove(__file__)
    except OSError:
        pass
    sys.exit(0 if ok else 1)


def swap():
    stage = os.path.join(files, stage_rel, "Sourcerer_files")
    stage_root = os.path.join(files, stage_rel)
    backup = os.path.join(files, "Userdata", "_update", "old")
    shutil.rmtree(backup, ignore_errors=True)
    os.makedirs(os.path.join(backup, "_root"))
    new = [n for n in os.listdir(stage) if n not in KEEP]
    old = [n for n in os.listdir(files) if n not in KEEP]
    moved, placed, roots = [], [], []
    try:
        for n in old:                                 # the old program aside...
            move(os.path.join(files, n), os.path.join(backup, n))
            moved.append(n)
        say("old version moved aside (%d items)" % len(moved))
        for n in new:                                 # ...the new one in its place
            move(os.path.join(stage, n), os.path.join(files, n))
            placed.append(n)
        for n in os.listdir(stage_root):              # the launchers and README beside it
            src = os.path.join(stage_root, n)
            if os.path.isfile(src):
                dst = os.path.join(install, n)
                if os.path.exists(dst):
                    move(dst, os.path.join(backup, "_root", n))
                move(src, dst)
                roots.append(n)
        say("new version in place")
    except Exception as e:
        say("update failed, putting the old version back: %s" % e)
        try:
            for n in placed:
                shutil.rmtree(os.path.join(files, n), ignore_errors=True) \
                    if os.path.isdir(os.path.join(files, n)) else os.remove(os.path.join(files, n))
            for n in moved:
                move(os.path.join(backup, n), os.path.join(files, n))
            for n in roots:
                saved = os.path.join(backup, "_root", n)
                if os.path.exists(saved):
                    move(saved, os.path.join(install, n))
            say("old version restored")
        except Exception as e2:
            say("RESTORE FAILED: %s -- the old version is in %s" % (e2, backup))
        return False
    shutil.rmtree(os.path.join(files, "Userdata", "_update"), ignore_errors=True)
    return True


try:
    say("waiting for Sourcerer to close")
    deadline = time.time() + 120
    while any(alive(p) for p in pids) and time.time() < deadline:
        time.sleep(0.3)
    time.sleep(1.5)        # the window's last processes go meanwhile
    if stage_rel == "-":
        say("restarting")
        finish(True)
    finish(swap())
except SystemExit:
    raise
except BaseException:
    say("the update helper broke: " + traceback.format_exc().replace("\n", " | "))
    finish(False)
"""
