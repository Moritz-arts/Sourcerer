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
HELPER = r'''
import datetime, os, shutil, subprocess, sys, time

a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
install, stage_rel = a["--install"], a["--stage"]
pids = [int(p) for p in a["--pids"].split(",") if p]
files = os.path.join(install, "Sourcerer_files")
bak = files + ".bak"
lines = []


def say(m):
    lines.append("%s  %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), m))


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


def start_again():
    env = dict(os.environ, SOURCERER_AFTER_UPDATE="1")
    if os.name == "nt":
        os.environ.update(env)
        os.startfile(os.path.join(install, "start-windows.bat"))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", os.path.join(install, "start-macos.command")], env=env)
    else:
        logf = open(os.path.join(files, "Userdata", "Logs", "console.log"), "a")
        subprocess.Popen(["sh", os.path.join(install, "start-linux.sh"), "--no-open"
                          if os.environ.get("SOURCERER_TEST") else "--browser"], env=env,
                         stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                         start_new_session=True, cwd=install)


def finish(ok):
    try:
        os.makedirs(os.path.join(files, "Userdata", "Logs"), exist_ok=True)
        with open(os.path.join(files, "Userdata", "Logs", "update.log"), "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    try:
        start_again()
    except Exception:
        pass
    try:
        os.remove(__file__)
    except OSError:
        pass
    sys.exit(0 if ok else 1)


say("waiting for Sourcerer to close")
deadline = time.time() + 90
while any(alive(p) for p in pids) and time.time() < deadline:
    time.sleep(0.3)
time.sleep(1.5)        # the launcher's console finishes its last lines meanwhile
if stage_rel == "-":
    say("restarting")
    finish(True)

# The rename is the test that counts: on Windows it fails for as long as
# anything still holds the folder or a file in it.
deadline = time.time() + 90
while True:
    try:
        os.rename(files, bak)
        break
    except OSError as e:
        if time.time() > deadline:
            say("could not move the old version aside: %s" % e)
            finish(False)
        time.sleep(0.5)
say("old version moved aside")
try:
    os.rename(os.path.join(bak, stage_rel, "Sourcerer_files"), files)
    for keep in ("Userdata", "venv"):
        if os.path.exists(os.path.join(bak, keep)):
            os.rename(os.path.join(bak, keep), os.path.join(files, keep))
    stage = os.path.join(files, stage_rel)          # travelled with Userdata
    for name in os.listdir(stage):
        src = os.path.join(stage, name)
        if os.path.isfile(src):
            os.replace(src, os.path.join(install, name))
    say("new version in place")
except Exception as e:
    say("update failed, putting the old version back: %s" % e)
    try:
        if os.path.exists(files):
            for keep in ("Userdata", "venv"):
                inner = os.path.join(files, keep)
                if os.path.exists(inner) and not os.path.exists(os.path.join(bak, keep)):
                    os.rename(inner, os.path.join(bak, keep))
            shutil.rmtree(files, ignore_errors=True)
        os.rename(bak, files)
        say("old version restored")
    except Exception as e2:
        say("RESTORE FAILED: %s -- the old version is in %s" % (e2, bak))
    finish(False)
shutil.rmtree(bak, ignore_errors=True)
shutil.rmtree(os.path.join(files, "Userdata", "_update"), ignore_errors=True)
say("done")
finish(True)
'''
