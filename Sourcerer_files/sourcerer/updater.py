"""Updates and repairs: Sourcerer.zip from GitHub, swapped in by a helper.

Two channels, chosen in Settings:

    stable   the newest published release and its Sourcerer.zip
    beta     the main branch: GitHub's own archive of its newest commit (nothing is
             uploaded for it; GitHub's releases hold the Stable version only)

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
import base64
import datetime
import logging
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import requests

from . import config, net

log = logging.getLogger(__name__)
API = "https://api.github.com/repos/%s" % config.REPO
STAGE_REL = "Userdata/_update/new"             # relative to Sourcerer_files
REQUIRED = ("Sourcerer_files/VERSION", "Sourcerer_files/launch.py",
            "Sourcerer_files/app.py", "start-windows.bat")
# The standalone builds are updated by hand (see install): the installer, disk image or AppImage
# of this system -- a portable copy takes the same version from the same release.
if not config.FROZEN:
    ASSET = "Sourcerer.zip"
elif sys.platform == "win32":
    ASSET = "Sourcerer-Setup.exe"
elif sys.platform == "darwin":
    ASSET = "Sourcerer-macOS-%s.dmg" % ("arm64" if platform.machine() == "arm64" else "x86_64")
else:
    ASSET = "Sourcerer-x86_64.AppImage" if config.APPIMAGE else "Sourcerer-Linux.tar.gz"


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def check(channel):
    """What the channel offers: {"version", "available", "url", "notes", "page"}."""
    # The standalone apps are built for releases only; there is no binary of the main branch.
    return _check_main() if channel == "beta" and not config.FROZEN else _check_release()


def _check_main():
    """Beta: the newest commit of main. Asked by commit, not by branch -- a branch URL is cached
    for minutes -- and the version is read from that same commit's VERSION."""
    head = net.get_json(API + "/commits/main")
    sha = head["sha"]
    found = net.get_json(API + "/contents/Sourcerer_files/VERSION", {"ref": sha})
    version = base64.b64decode(found["content"]).decode("utf-8").strip()
    message = ((head.get("commit") or {}).get("message") or "").strip().splitlines()
    return {"channel": "beta", "current": config.VERSION, "version": version,
            "newer": version_tuple(version) > version_tuple(config.VERSION),
            "available": version_tuple(version) > version_tuple(config.VERSION),
            "url": "https://codeload.github.com/%s/zip/%s" % (config.REPO, sha),
            "notes": message[0] if message else "", "page": head.get("html_url") or "", "manual": False}


def _check_release():
    try:
        rel = net.get_json(API + "/releases/latest")
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 404:
            raise
        rel = {}                                   # nothing published yet
    version = (rel.get("tag_name") or "").lstrip("vV")
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == ASSET), None)
    newer = version_tuple(version) > version_tuple(config.VERSION)
    # "newer" without "available": the release is out, its files are still being attached (the
    # installers come after Sourcerer.zip) -- "up to date" would be a lie.
    return {"channel": "stable", "current": config.VERSION, "version": version,
            "newer": newer, "available": bool(asset and newer),
            "url": asset["browser_download_url"] if asset else "",
            "sha256": (asset.get("digest") or "").removeprefix("sha256:") if asset else "",
            "notes": rel.get("body") or "", "page": rel.get("html_url") or "",
            "manual": config.FROZEN and not installed()}


DETACHED, NEW_GROUP, NO_WINDOW = 0x00000008, 0x00000200, 0x08000000     # Windows creation flags


def _detached(args, flags=0, **kwargs):
    """Start a program that outlives this one: no stdio of ours, a process group (a session off
    Windows) of its own. `flags` are the Windows creation flags; cwd and env can be given."""
    opts = {"cwd": tempfile.gettempdir(), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL, "close_fds": True}
    opts.update(kwargs)
    if os.name == "nt":
        opts["creationflags"] = flags
    else:
        opts["start_new_session"] = True
    return subprocess.Popen(args, **opts)


# A one-file build unpacks itself to a temp folder, and a program it starts from the same file shares
# that folder (that is what keeps every gallery-dl run quick). A *new* Sourcerer -- the restarted one,
# the one the installer starts -- must unpack its own: the old folder goes with the old process.
INDEPENDENT = {"PYINSTALLER_RESET_ENVIRONMENT": "1"}


def installed():
    """A copy that Sourcerer-Setup.exe put in place -- its uninstaller sits beside the program.

    Only such a copy updates itself: the installer does the swap (closes Sourcerer, clears the old
    program files, keeps Userdata, starts the new one). A portable copy, a macOS app and an
    AppImage are replaced by hand -- the app, or the one file, as a whole.
    """
    return config.FROZEN and sys.platform == "win32" and (config.INSTALL / "unins000.exe").is_file()


# Run by a hidden cmd, paths only through the environment (a user name may not survive the console's
# code page) and the system's own tools by full path (a stray find.exe or ping.bat on the PATH or in
# the temp folder must not stand in). No ( ) blocks, ping is the sleep (see the update helper).
# The cmd does NOT wait for the program itself: Setup does (InitializeSetup in Sourcerer.iss), where
# "is Sourcerer.exe in use" can be asked the way Setup asks it. A cmd cannot: appending to a running
# exe succeeds (`>>` asks for append access only, which a running image allows) -- CI showed Setup
# started at once and sitting on the running program. Setup never forces the program closed: when it
# stays open for /WAIT seconds, Setup stops with code 1 and the update is not run.
# The new Sourcerer is started by the installer itself (/START=1); the old one only when Setup failed
# (or the installer's [Run] entry did not start anything) -- and then the reason is a block in
# update.log, which the next start reports (desktop._after_update). Success writes nothing there: the
# new Sourcerer would read the log before this script got to it.
SETUP_WAIT = 60                       # seconds Setup gives the program to close
SETUP_CMD = "\r\n".join([
    "@echo off",
    'echo started>"%SOURCERER_MARK%"',
    'start "" /wait "%SOURCERER_SETUP%" /SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /START=1 /WAIT=%SOURCERER_WAIT% /LOG="%SOURCERER_SETUP_LOG%"',
    "set code=%errorlevel%",
    'if "%code%"=="0" goto ok',
    'echo %SOURCERER_STAMP%  update by Setup>>"%SOURCERER_UPDATE_LOG%"',
    'echo setup failed (code %code%; code 1 means Sourcerer did not close in time); Sourcerer starts again; details in Userdata\\Logs\\setup.log>>"%SOURCERER_UPDATE_LOG%"',
    'start "" "%SOURCERER_EXE%" --restart',
    "goto end",
    ":ok",
    "set n=0",
    ":alive",
    '"%SOURCERER_SYS%\\tasklist.exe" /FI "IMAGENAME eq %SOURCERER_IMAGE%" /NH 2>nul | "%SOURCERER_SYS%\\find.exe" /I "%SOURCERER_IMAGE%" >nul',
    'if "%errorlevel%"=="0" goto end',
    "set /a n+=1",
    "if %n% geq 20 goto lost",
    '"%SOURCERER_SYS%\\ping.exe" -n 2 127.0.0.1 >nul',
    "goto alive",
    ":lost",
    'start "" "%SOURCERER_EXE%" --restart',
    ":end",
    'del "%SOURCERER_MARK%" 2>nul',
    '(goto) 2>nul & del "%~f0"',
    "",
])


def run_setup_script(exe, setup, log_dir, wait=SETUP_WAIT):
    """Windows, installed: a hidden cmd runs `setup` (it waits for `exe` to be free, `wait` seconds).

    Setup run while this program was still going down -- the one-file build is two processes, the
    window already gone -- reached "Closing applications...", its restart manager sat there until it
    gave up and rolled the update back. Setup itself now waits for the program to let go (and never
    forces it); the script gives it its own log (Userdata/Logs/setup.log) and, when Setup fails,
    starts the old Sourcerer again: no exit path leaves the program closed. It writes a mark first thing; if
    that does not appear (cmd.exe blocked, the script removed by a scanner) this raises, and the
    caller must not shut Sourcerer down."""
    log_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="sourcerer-update-", suffix=".cmd")
    script = pathlib.Path(name)
    mark = script.with_suffix(".started")
    proc = None
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="") as f:
            f.write(SETUP_CMD)
        env = dict(os.environ, SOURCERER_EXE=str(exe), SOURCERER_IMAGE=pathlib.Path(exe).name,
                   SOURCERER_SETUP=str(setup), SOURCERER_MARK=str(mark),
                   SOURCERER_SETUP_LOG=str(log_dir / "setup.log"), SOURCERER_UPDATE_LOG=str(log_dir / "update.log"),
                   SOURCERER_STAMP=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   SOURCERER_SYS=os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"),
                   SOURCERER_WAIT=str(wait), **INDEPENDENT)
        # By its bare name from the temp folder (cwd): a path with ( ) & in it -- C:\Users\Jo (work) --
        # would be torn apart by cmd /c's quote handling. /d: no AutoRun commands.
        proc = _detached(["cmd.exe", "/d", "/c", script.name], NO_WINDOW | NEW_GROUP, env=env)
        for _ in range(50):                                        # 5 s for a cold, scanned cmd.exe
            if mark.exists():
                return
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        raise RuntimeError("The update helper did not start (is cmd.exe blocked here?). "
                           "Sourcerer keeps running; install the new Sourcerer-Setup.exe by hand.")
    except BaseException:
        if proc is not None and proc.poll() is None:
            proc.kill()
        script.unlink(missing_ok=True)
        mark.unlink(missing_ok=True)
        raise


def _setup_after_exit(setup):
    run_setup_script(pathlib.Path(sys.executable), setup, config.LOG_DIR)


def _install_setup(channel):
    """Windows, installed: download the newest Sourcerer-Setup.exe and run it silently."""
    if not installed():
        raise RuntimeError("The standalone Sourcerer is updated by hand: download %s." % ASSET)
    info = _check_release()
    if not info["url"]:
        raise RuntimeError("The latest release has no %s." % ASSET)
    if not info["available"]:
        raise RuntimeError("Sourcerer is up to date.")
    shutil.rmtree(config.UPDATE_DIR, ignore_errors=True)
    part, sha, _ext, _name = net.download(info["url"], config.UPDATE_DIR)
    setup = config.UPDATE_DIR / ASSET
    os.replace(part, setup)
    # GitHub states each asset's SHA-256; what came down must be exactly that file, not an error page.
    if info.get("sha256") and sha != info["sha256"]:
        raise RuntimeError("The download does not match the release's checksum.")
    _setup_after_exit(setup)
    log.info("update to v%s started: %s", info["version"], setup)
    return info


def install(channel):
    if config.FROZEN:
        return _install_setup(channel)
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
    if config.FROZEN:
        raise RuntimeError("The standalone Sourcerer cannot reinstall itself: download %s." % ASSET)
    url = "https://codeload.github.com/%s/zip/refs/tags/v%s" % (config.REPO, config.VERSION)
    _stage(url, config.VERSION)
    _launch_helper(swap=True)


def restart():
    """Start Sourcerer again once this one has closed."""
    if config.FROZEN:
        # The new one waits (--restart) until this one no longer answers; started at once it
        # would find this one running and leave. No shell, no helper script: the exe is enough.
        # An AppImage's inner binary vanishes with its mount once this process is gone.
        _detached([config.APPIMAGE or sys.executable, "--restart"], DETACHED | NEW_GROUP,
                  cwd=str(config.INSTALL), env=dict(os.environ, **INDEPENDENT))
        return
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
    _detached(args, DETACHED | NEW_GROUP | NO_WINDOW)
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
