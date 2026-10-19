"""gallery-dl, run as a program of its own, for sites whose insides change every few weeks.

X is the reason: its web API needs rotating query ids, about forty feature
flags and a per-request transaction id computed from its own scripts.
gallery-dl follows those changes almost weekly; a copy of our own would stay
broken until the next Sourcerer release. gallery-dl only *lists* here (-N
prints one JSON line per file and downloads nothing); Sourcerer downloads the
files itself, through net.py, with its own names and duplicate rules.

A separate process, not an import: gallery-dl is GPL-2.0, and a pip upgrade
of it (Settings > Updates) reaches the next X fix without a Sourcerer release.
Its cookies come from a config file written for the one run (mode 600, then
deleted) -- never the command line, which other programs can read. Its cache
holds login state and lives in Userdata, like everything Sourcerer keeps.
"""
import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
import threading

from .. import config, net

log = logging.getLogger(__name__)
DIR = config.USERDATA / "gallery-dl"
CACHE = DIR / "cache.sqlite3"
PAGE = 20                     # files per page handed to sync's scan, for its early stop
_count = [0]
# One gallery-dl per site reads at a time: its pacing (sleep-request) lives
# inside one process, so two of them -- a sync and a link check -- would each
# ask at full speed. The lock is held while a page is read, not while a caller
# keeps a listing suspended (a gallery does, between pages): two X accounts on
# one card, or a sync during an open gallery, would otherwise wait for it
# forever. Whoever cannot get its turn in WAIT_INFO seconds gives up.
_busy = {}
_busy_lock = threading.Lock()
WAIT_INFO = 30


def _site_lock(section):
    with _busy_lock:
        return _busy.setdefault(section, threading.Lock())


class Failed(RuntimeError):
    """gallery-dl stopped with an error; .auth says whether a login would help."""

    def __init__(self, text, auth=False, slow=False):
        super().__init__(text)
        self.auth, self.slow = auth, slow


def available():
    return importlib.util.find_spec("gallery_dl") is not None


def upgrade():
    """pip install -U gallery-dl into Sourcerer's own environment -- the way X's
    fixes reach users between Sourcerer releases. Returns the version after."""
    if config.FROZEN:
        raise RuntimeError("The standalone Sourcerer carries its own gallery-dl; a new Sourcerer "
                           "release brings the newest one.")
    env = dict(os.environ, PIP_CACHE_DIR=str(config.ROOT / "venv" / "pip-cache"),
               PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONNOUSERSITE="1")
    kwargs = {"capture_output": True, "timeout": 600, "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000           # CREATE_NO_WINDOW
    done = subprocess.run([_python(), "-m", "pip", "install", "-U", "-q", "gallery-dl"], **kwargs)
    if done.returncode:
        raise RuntimeError("pip could not update gallery-dl: %s" %
                           (done.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"])[-1])
    log.info("gallery-dl is now %s", version())
    return version()


def version():
    try:
        from importlib.metadata import version as v
        return v("gallery-dl")
    except Exception:
        return ""


def _python():
    """The venv's interpreter. On Windows python.exe, not the pythonw.exe
    Sourcerer runs in: a console program whose pipes are certain to work,
    started with CREATE_NO_WINDOW so no console flashes up."""
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("pythonw.exe"):
        console = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.isfile(console):
            return console
    return exe


def _config(section, options):
    """section: the extractor's category -- gallery-dl reads extractor.<category> for it. None: the options
    are for whichever extractor the URL finds (extractor.<option>): a forum is found by a name of its own
    making, or by one gallery-dl knows it under, and options kept under another name were ignored."""
    DIR.mkdir(parents=True, exist_ok=True)
    _count[0] += 1
    path = DIR / ("run-%d-%d.json" % (os.getpid(), _count[0]))
    conf = {"extractor": dict({"input": False}, **options) if section is None else {"input": False, section: options}}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(conf, f)
    return path


def _command(conf, args, url):
    # The exe has no "python -m": app.py runs gallery-dl when started with --gallery-dl.
    run = [sys.executable, "--gallery-dl"] if config.FROZEN else [_python(), "-m", "gallery_dl"]
    return run + ["--config-ignore", "-c", str(conf),
            "--cache-file", str(CACHE), "--no-input"] + args + [url]


def _start(cmd):
    # In the one-file build gallery-dl is the program itself again; it shares the parent's unpacked
    # folder unless told otherwise, so it must not be told otherwise (see updater.INDEPENDENT).
    env = {k: v for k, v in os.environ.items() if k != "PYINSTALLER_RESET_ENVIRONMENT"}
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "stdin": subprocess.DEVNULL,
              "cwd": str(DIR), "env": dict(env, PYTHONIOENCODING="utf-8")}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000           # CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)


def _failure(code, errors, lines=()):
    """What a non-zero exit means, from gallery-dl's exit bits and what it said."""
    text = errors[-1] if errors else "gallery-dl stopped (exit %d)" % code
    text = re.sub(r"^\[[\w.-]+\]\[\w+\]\s*", "", text)
    joined = " ".join(list(errors) + list(lines))
    # 16: authentication / authorisation. An expired X session shows up as a
    # redirect to the login page and a bare "403 Forbidden" instead.
    auth = bool(code & 16) or "login page" in joined or "AuthRequired" in joined
    slow = bool(code & 8) or "Rate limit" in joined or "ChallengeError" in joined
    return Failed(text, auth=auth, slow=slow)


def items(url, section, options, fields, lock=None):
    """Yield pages (lists) of dicts, one per file, newest first.

    fields: {name: gallery-dl format expression}, e.g. {"url": "{_url!j}"}.
    lock: what one read at a time is per (the site; a forum is one host, though gallery-dl's section for
    every forum is the same), by default the section.
    Stopping early -- closing this generator -- ends the gallery-dl process.
    """
    fmt = "prepare:{{" + ",".join('"%s":%s' % (k, v) for k, v in fields.items()) + "}}"
    lock = _site_lock(lock or section)
    listing = _items(url, section, options, fmt)
    try:
        while True:
            if not lock.acquire(timeout=WAIT_INFO):
                raise net.SlowDown("busy with another listing of this site; try again in a moment")
            try:
                page = next(listing, None)
            finally:
                lock.release()
            if page is None:
                return
            yield page
    finally:
        listing.close()


def _items(url, section, options, fmt):
    conf = _config(section, options)
    proc = _start(_command(conf, ["-N", fmt], url))
    errors, lines = [], []

    def read_errors():
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").strip()
            lines.append(line)
            if "][error]" in line:
                errors.append(line)
            elif "][warning]" in line:
                log.info("gallery-dl: %s", line)
    reader = threading.Thread(target=read_errors, daemon=True)
    reader.start()
    try:
        page = []
        for raw in proc.stdout:
            try:
                page.append(json.loads(raw.decode("utf-8")))
            except ValueError:
                continue
            if len(page) >= PAGE:
                yield page
                page = []
        if page:
            yield page
        code = proc.wait()
        reader.join(5)
        if code:
            raise _failure(code, errors, lines)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        conf.unlink(missing_ok=True)


def info(url, section, options):
    """The JSON gallery-dl gives for a small listing (a profile's info): its messages."""
    lock = _site_lock(section)
    if not lock.acquire(timeout=WAIT_INFO):
        raise net.SlowDown("busy with another listing of this site; try again in a moment")
    try:
        return _info(url, section, options)
    finally:
        lock.release()


def _info(url, section, options):
    conf = _config(section, options)
    try:
        proc = _start(_command(conf, ["-j"], url))
        out, err = proc.communicate(timeout=120)
    finally:
        conf.unlink(missing_ok=True)
    lines = err.decode("utf-8", "replace").splitlines()
    if proc.returncode:
        raise _failure(proc.returncode, [l for l in lines if "][error]" in l], lines)
    messages = json.loads(out.decode("utf-8") or "[]")
    # -j reports an error as a message [-1, {"error": ..., "message": ...}] and exits 0.
    for m in messages:
        if m and m[0] == -1:
            e = m[-1] if isinstance(m[-1], dict) else {}
            name = e.get("error", "")
            raise Failed("%s: %s" % (name, e.get("message", "")),
                         auth=name.startswith("Auth"), slow=name == "ChallengeError")
    return messages
