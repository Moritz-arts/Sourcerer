"""Start a built download the way a user would and check that it works.

    python .github/exe/smoke.py <asset> [--window]

<asset> is what build.py made: Sourcerer-Windows.zip, Sourcerer-Setup.exe (installed silently),
Sourcerer-Linux.tar.gz, Sourcerer-x86_64.AppImage or Sourcerer-macOS-<arch>.dmg.

What a source start never needed and the frozen one can get wrong: the static files and VERSION
in the bundle, where Userdata lands, TLS certificates (the update check asks GitHub), gallery-dl
as a second run of the program (all its extractors present), the second start finding the first.
--window also starts it as a user does and reports whether the app window came up -- reported,
not enforced: a CI runner is no desktop.
"""
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

PORT = 8791
failed = []


def check(ok, what, detail=""):
    print("%s  %s %s" % ("ok  " if ok else "FAIL", what, detail), flush=True)
    if not ok:
        failed.append(what)


def get(path, port=PORT):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:%d%s" % (port, path), timeout=30) as r:
        return r.status, r.read()


def wait_for(port, seconds=90):
    end = time.time() + seconds
    while time.time() < end:
        try:
            return json.loads(get("/api/ping", port)[1])
        except OSError:
            time.sleep(0.5)
    return None


def stop(proc):
    # An AppImage's runtime starts the program as a child and waits for it: stopping only the
    # runtime leaves the program (and its port) behind. POSIX starts are a process group of their own.
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except OSError:                                         # already gone (a restart ends the first one)
        pass
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def unpack(asset, work, home):
    """(program, where Userdata must land, environment) for an asset, unpacked or installed into work."""
    env = dict(os.environ, HOME=str(home))
    env.pop("XDG_DATA_HOME", None)
    name = asset.name
    if name.endswith(".zip"):
        with zipfile.ZipFile(asset) as z:
            z.extractall(work / "app")
        # One file; Userdata is made beside it on the first start.
        return work / "app" / "Sourcerer.exe", work / "app" / "Userdata", env
    if name.endswith(".tar.gz"):
        with tarfile.open(asset) as t:
            t.extractall(work / "app")
        return work / "app" / "Sourcerer" / "Sourcerer", work / "app" / "Sourcerer" / "Userdata", env
    if name.endswith(".AppImage"):
        exe = work / name
        shutil.copy(asset, exe)
        exe.chmod(0o755)
        env["APPIMAGE_EXTRACT_AND_RUN"] = "1"           # no FUSE on a CI machine
        return exe, home / ".local" / "share" / "Sourcerer" / "Userdata", env
    if name.endswith(".dmg"):
        mount = work / "mnt"
        mount.mkdir()
        subprocess.check_call(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(asset)])
        try:
            shutil.copytree(mount / "Sourcerer.app", work / "app" / "Sourcerer.app", symlinks=True)
        finally:
            subprocess.call(["hdiutil", "detach", "-force", str(mount)])
        return (work / "app" / "Sourcerer.app" / "Contents" / "MacOS" / "Sourcerer",
                home / "Library" / "Application Support" / "Sourcerer" / "Userdata", env)
    if name.endswith("Setup.exe"):
        target = work / "app"
        subprocess.check_call([str(asset), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
                               "/NOICONS", "/DIR=" + str(target), "/LOG=" + str(work / "setup.log")])
        return target / "Sourcerer.exe", target / "Userdata", env
    sys.exit("don't know how to test " + name)


def update_over(asset, exe, data):
    """The installer over an existing install -- what an update is.

    First over a copy laid out as up to v0.21 (a Sourcerer_files folder with Userdata inside): the old
    program files must be gone, the user's data moved beside the executable. Then over the new layout:
    the data must stay put. The install folder itself is never cleared."""
    folder = exe.parent / "Sourcerer_files"
    stale_file, stale_dir = folder / "old_module.pyd", folder / "old_package"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_bytes(b"old")
    (stale_dir / "deep").mkdir(parents=True)
    (stale_dir / "deep" / "x.py").write_text("old")
    (folder / "Userdata").mkdir()
    (folder / "Userdata" / "mine.txt").write_text("my cards")
    neighbour = exe.parent / "somebody-elses-file.txt"        # an install folder may be anything
    neighbour.write_text("not ours")
    check((exe.parent / "unins000.exe").is_file(), "the install has its uninstaller (that is what lets it update itself)")

    def run_setup(tag):
        subprocess.check_call([str(asset), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
                               "/NOICONS", "/DIR=" + str(exe.parent), "/LOG=" + str(exe.parent.parent / (tag + ".log"))])

    run_setup("update-1")
    check(not stale_file.exists() and not stale_dir.exists(), "an update removes what the new version no longer has")
    check((data / "mine.txt").is_file() and (data / "mine.txt").read_text() == "my cards",
          "an update moves an old Userdata beside the executable and keeps it")
    check(not folder.exists(), "the old program folder is gone")
    check(neighbour.is_file(), "an update never clears the install folder itself")
    check(exe.is_file(), "the program is in place after the update")
    run_setup("update-2")
    check((data / "mine.txt").read_text() == "my cards" and exe.is_file(), "a second update keeps Userdata where it is")


def restart_works(data, old_pid):
    """Settings > Repair > Restart: the old one goes, a new one answers on its own. In a one-file build the
    new one has to unpack a folder of its own (the old one's goes with it)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    opener.open(urllib.request.Request("http://127.0.0.1:%d/api/repair" % PORT,
                                       data=json.dumps({"action": "restart"}).encode(),
                                       headers={"Content-Type": "application/json"}), timeout=30).close()
    end = time.time() + 90
    while time.time() < end:
        try:
            info = json.loads((data / "running.json").read_text(encoding="utf-8"))
            if info["pid"] != old_pid and wait_for(info["port"], 2):
                return info
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(1)
    return None


def kill(pid):
    if os.name == "nt":
        subprocess.call(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def main():
    asset = pathlib.Path(sys.argv[1]).resolve()
    work = pathlib.Path(tempfile.mkdtemp(prefix="sourcerer-smoke-"))
    home = work / "home"
    home.mkdir()
    exe, data, env = unpack(asset, work, home)
    check(exe.is_file(), "%s unpacks to a program" % asset.name, str(exe))
    if asset.name.endswith("Setup.exe"):
        update_over(asset, exe, data)
    logs = data / "Logs"

    def start(*args):
        return subprocess.Popen([str(exe)] + list(args), cwd=str(work), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=os.name != "nt")

    # gallery-dl: the program run again with --gallery-dl, output through pipes as _gdl reads it.
    done = subprocess.run([str(exe), "--gallery-dl", "--version"], capture_output=True, timeout=180, env=env)
    check(done.returncode == 0 and done.stdout.strip(), "gallery-dl --version", done.stdout.decode().strip())
    done = subprocess.run([str(exe), "--gallery-dl", "--list-extractors"], capture_output=True, timeout=300, env=env)
    check(done.returncode == 0 and b"Twitter" in done.stdout and len(done.stdout.splitlines()) > 1000,
          "gallery-dl knows its extractors (X among them)", "%d lines" % len(done.stdout.splitlines()))

    began = time.time()
    app = start("--no-open", "--port", str(PORT))
    try:
        ping = wait_for(PORT)
        check(bool(ping), "starts and answers", "in %.1f s %s" % (time.time() - began, ping))
        if ping:
            status, body = get("/")
            check(status == 200 and b"Sourcerer" in body, "page is served")
            check(get("/static/app.js")[0] == 200 and get("/static/logo.svg")[0] == 200, "static files are served")
            info = json.loads(get("/api/info")[1])
            check(info["frozen"] and info["gallery_dl"], "info says frozen, gallery-dl present", info["gallery_dl"])
            check(ping["version"] == info["version"] and (data / "sourcerer.db").is_file(),
                  "version %s, Userdata where it belongs" % info["version"], info["userdata"])
            try:
                upd = json.loads(get("/api/update/check?channel=stable")[1])
                # An installed Windows copy updates itself; every other standalone copy is updated by hand.
                installed = asset.name.endswith("Setup.exe")
                check(upd.get("manual") is (not installed) and info["updatable"] is installed,
                      "update check reaches GitHub (TLS); %s" % ("updates itself" if installed else "updated by hand"),
                      str(upd.get("version")))
            except urllib.error.HTTPError as e:
                # GitHub's API rations an address, and a runner's is shared: "refused access (403)" is the
                # site talking, so TLS works. "cannot connect" is what a missing certificate looks like.
                said = json.loads(e.read().decode("utf-8", "replace") or "{}").get("error", "")
                check("cannot connect" not in said, "update check reaches GitHub (TLS)", said)
            second = subprocess.run([str(exe), "--no-open"], cwd=str(work), env=env, timeout=60)
            check(second.returncode == 0, "a second start leaves at once")
            began = time.time()
            again = restart_works(data, ping["pid"])
            check(bool(again), "Restart brings Sourcerer back", "in %.1f s" % (time.time() - began))
            if again:
                kill(again["pid"])
    finally:
        stop(app)

    if "--window" in sys.argv:
        shown = start("--port", str(PORT + 1))
        try:
            check(bool(wait_for(PORT + 1)), "starts as a user starts it")
            time.sleep(8)                                         # pywebview gives up, if it will, by now
            try:
                has_window = json.loads(get("/api/info", PORT + 1)[1])["window"]
                print("WINDOW: %s" % ("app window" if has_window else "browser fallback"), flush=True)
            except OSError as e:
                print("WINDOW: unknown (%s)" % e, flush=True)
        finally:
            stop(shown)

    for name in ("sourcerer.log", "console.log"):
        path = logs / name
        if path.is_file():
            print("---- %s (tail) ----" % name)
            print("\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]))
    if failed:
        sys.exit("FAILED: " + "; ".join(failed))
    print("all good")


if __name__ == "__main__":
    main()
