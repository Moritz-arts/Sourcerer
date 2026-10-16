"""Start the built Sourcerer-Windows.zip the way a user would and check that it works.

    python .github/exe/smoke.py Sourcerer-Windows.zip [--window]

What a source start never needed and the frozen one can get wrong: the static files
and VERSION in the bundle, TLS certificates (the update check asks GitHub), gallery-dl
as a second run of the exe (all its extractors present), the second start finding the
first. --window also starts it as a user does and reports whether the app window came
up -- reported, not enforced: a CI runner is no desktop.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
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
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def start(exe, work, *args):
    return subprocess.Popen([str(exe)] + list(args), cwd=str(work), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    work = pathlib.Path(tempfile.mkdtemp(prefix="sourcerer-smoke-"))
    with zipfile.ZipFile(sys.argv[1]) as z:
        z.extractall(work)
    exe = work / ("Sourcerer.exe" if os.name == "nt" else "Sourcerer")
    if os.name != "nt":
        exe.chmod(0o755)
    logs = work / "Sourcerer_files" / "Userdata" / "Logs"

    # gallery-dl: the exe run again with --gallery-dl, output through pipes as _gdl reads it.
    done = subprocess.run([str(exe), "--gallery-dl", "--version"], capture_output=True, timeout=120)
    check(done.returncode == 0 and done.stdout.strip(), "gallery-dl --version", done.stdout.decode().strip())
    done = subprocess.run([str(exe), "--gallery-dl", "--list-extractors"], capture_output=True, timeout=300)
    check(done.returncode == 0 and b"Twitter" in done.stdout and len(done.stdout.splitlines()) > 1000,
          "gallery-dl knows its extractors (X among them)", "%d lines" % len(done.stdout.splitlines()))

    app = start(exe, work, "--no-open", "--port", str(PORT))
    try:
        ping = wait_for(PORT)
        check(bool(ping), "starts and answers", str(ping))
        if ping:
            version = (work / "Sourcerer_files" / "VERSION").read_text().strip()
            check(ping["version"] == version, "version is the bundled VERSION", ping["version"])
            status, body = get("/")
            check(status == 200 and b"Sourcerer" in body, "page is served")
            check(get("/static/app.js")[0] == 200 and get("/static/logo.svg")[0] == 200, "static files are served")
            info = json.loads(get("/api/info")[1])
            check(info["frozen"] and info["gallery_dl"], "info says frozen, gallery-dl present", info["gallery_dl"])
            check((work / "Sourcerer_files" / "Userdata" / "sourcerer.db").is_file(),
                  "Userdata is inside Sourcerer_files")
            try:
                upd = json.loads(get("/api/update/check?channel=stable")[1])
                check(upd.get("manual") is True and "error" not in upd, "update check reaches GitHub (TLS)",
                      str(upd.get("version")))
            except OSError as e:
                check(False, "update check reaches GitHub (TLS)", str(e))
            second = subprocess.run([str(exe), "--no-open"], cwd=str(work), timeout=60)
            check(second.returncode == 0, "a second start leaves at once")
    finally:
        stop(app)

    if "--window" in sys.argv:
        shown = start(exe, work, "--port", str(PORT + 1))
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
