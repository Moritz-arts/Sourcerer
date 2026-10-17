"""Build the standalone Sourcerer (PyInstaller) for the system this runs on, and package it.

    python .github/exe/build.py [out_dir]     (needs: pip install -r Sourcerer_files/requirements.txt pyinstaller)

Everything to publish ends up in <out_dir>/assets/:

    Windows   Sourcerer-Setup.exe             the installer (Inno Setup; per user, no admin)
              Sourcerer-Windows.zip           portable: Sourcerer.exe, one file
    macOS     Sourcerer-macOS-<arch>.dmg      the app, to drag into Applications
    Linux     Sourcerer-x86_64.AppImage       one file
              Sourcerer-Linux.tar.gz          portable: Sourcerer/Sourcerer, one file

As few files as can be (Pikura's install folder holds a handful): Windows and the Linux tar.gz are ONE
executable that unpacks itself to a temp folder when it starts (PyInstaller --onefile); the data beside
it is Userdata/, made on first start. The AppImage and the macOS app are one item each and hold the
unpacked program inside (an AppImage's mount, the app bundle), so they start without unpacking. In
both, Userdata lives in the user's data folder, see config.py.
"""
import os
import pathlib
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

import PyInstaller.__main__

REPO = pathlib.Path(__file__).resolve().parents[2]
FILES = REPO / "Sourcerer_files"
HERE = pathlib.Path(__file__).resolve().parent
APPIMAGETOOL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

# Files PyInstaller copies that the system already has. Windows 10 and newer ship the Universal C
# Runtime; its ~40 forwarder DLLs (api-ms-win-*) and ucrtbase.dll are only for Windows 7 and 8, which
# Python 3.12 and WebView2 have left behind. Not in the bundle = smaller, and a faster unpack.
DROP = {"win32": ("api-ms-win-", "ucrtbase.dll")}


def freeze(out, onefile):
    """Run PyInstaller; returns the folder holding the result (Sourcerer.exe / Sourcerer / Sourcerer.app)."""
    mode = "one" if onefile else "dir"
    spec_dir, dist, work = out / ("spec-" + mode), out / ("dist-" + mode), out / ("work-" + mode)
    sep = os.pathsep
    args = [
        str(FILES / "app.py"),
        "--name", "Sourcerer", "--windowed", "--onefile" if onefile else "--onedir",
        "--specpath", str(spec_dir), "--paths", str(FILES),
        "--add-data", "%s%sstatic" % (FILES / "static", sep),
        "--add-data", "%s%s." % (FILES / "VERSION", sep),
        # gallery-dl loads its extractors by name at run time, which no import scan sees.
        "--collect-submodules", "gallery_dl", "--copy-metadata", "gallery-dl",
        # Pulled in by libraries that only mention them; a build tool is not part of a program.
        "--exclude-module", "setuptools", "--exclude-module", "pkg_resources",
    ]
    if sys.platform == "darwin":
        args += ["--icon", str(HERE / "Sourcerer.icns"), "--osx-bundle-identifier", "io.github.moritz-arts.sourcerer"]
    elif not onefile:
        args += ["--contents-directory", "Sourcerer_files"]
    if sys.platform == "win32":
        args += ["--icon", str(HERE / "Sourcerer.ico")]
    if sys.platform in ("win32", "darwin"):
        # The window: pywebview on WebView2 (through pythonnet) or WKWebView; their libraries are
        # found by hooks only when asked for. Without them Sourcerer still starts, in the browser.
        # Linux has no such bridge in the bundle (GTK/Qt come from the system): browser only.
        for pkg in ("webview",) + (("pythonnet", "clr_loader") if sys.platform == "win32" else ()):
            args += ["--collect-all", pkg]
    # Through a spec file, because the command line cannot drop a binary from the bundle.
    spec_dir.mkdir(parents=True)
    subprocess.check_call([sys.executable, "-m", "PyInstaller.utils.cliutils.makespec"] + args)
    spec = spec_dir / "Sourcerer.spec"
    text = spec.read_text(encoding="utf-8")
    drop = DROP.get(sys.platform)
    if drop:
        keep = "a.binaries = [b for b in a.binaries if not b[0].lower().startswith(%r)]\npyz = PYZ(a.pure)" % (drop,)
        assert "pyz = PYZ(a.pure)" in text
        spec.write_text(text.replace("pyz = PYZ(a.pure)", keep), encoding="utf-8")
    PyInstaller.__main__.run([str(spec), "--noconfirm", "--clean", "--distpath", str(dist), "--workpath", str(work)])
    return dist


def size_mb(path):
    return path.stat().st_size / 1e6


def windows(out, assets, version):
    exe = freeze(out, onefile=True) / "Sourcerer.exe"
    print("Sourcerer.exe: one file, %.1f MB" % size_mb(exe))
    with zipfile.ZipFile(assets / "Sourcerer-Windows.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(exe, "Sourcerer.exe")
    iscc = shutil.which("iscc") or next((str(p) for p in (
        pathlib.Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        pathlib.Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe") if p.is_file()), None)
    if not iscc:
        sys.exit("Inno Setup (ISCC.exe) not found -- choco install innosetup")
    subprocess.check_call([iscc, "/Qp", "/DVersion=" + version, "/DExe=" + str(exe),
                           "/DOutputDir=" + str(assets), "/DIcon=" + str(HERE / "Sourcerer.ico"),
                           str(HERE / "Sourcerer.iss")])


def macos(out, assets, version):
    app = freeze(out, onefile=False) / "Sourcerer.app"
    arch = "arm64" if platform.machine() == "arm64" else "x86_64"
    with tempfile.TemporaryDirectory() as tmp:
        stage = pathlib.Path(tmp) / "Sourcerer"
        stage.mkdir()
        # symlinks=True: a bundle's frameworks are links; copying them as files breaks the signature.
        shutil.copytree(app, stage / "Sourcerer.app", symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        subprocess.check_call(["hdiutil", "create", "-volname", "Sourcerer", "-srcfolder", str(stage),
                               "-ov", "-format", "UDZO", str(assets / ("Sourcerer-macOS-%s.dmg" % arch))])


def linux(out, assets, version):
    # The portable file: one executable, unpacking itself on every start.
    exe = freeze(out, onefile=True) / "Sourcerer"
    print("Sourcerer: one file, %.1f MB" % size_mb(exe))
    with tarfile.open(assets / "Sourcerer-Linux.tar.gz", "w:gz") as t:
        t.add(exe, arcname="Sourcerer/Sourcerer")      # keeps the executable bit
    # The AppImage: the unpacked program inside, so it starts at once from its mount.
    bundle = freeze(out, onefile=False) / "Sourcerer"
    with tempfile.TemporaryDirectory() as tmp:
        appdir = pathlib.Path(tmp) / "Sourcerer.AppDir"
        shutil.copytree(bundle, appdir / "usr" / "bin", symlinks=True)
        shutil.copy(HERE / "Sourcerer.png", appdir / "sourcerer.png")
        (appdir / ".DirIcon").symlink_to("sourcerer.png")
        (appdir / "sourcerer.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Sourcerer\nComment=Keeps artists' media in sync\n"
            "Exec=Sourcerer\nIcon=sourcerer\nCategories=Network;Graphics;\nTerminal=false\n", encoding="utf-8")
        run = appdir / "AppRun"
        run.write_text('#!/bin/sh\nexec "$(dirname "$(readlink -f "$0")")/usr/bin/Sourcerer" "$@"\n', encoding="utf-8")
        run.chmod(0o755)
        tool = pathlib.Path(tmp) / "appimagetool"
        urllib.request.urlretrieve(APPIMAGETOOL, tool)
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
        # No FUSE on a build machine: let the tool unpack itself and run from there.
        subprocess.check_call([str(tool), "--appimage-extract-and-run", str(appdir),
                               str(assets / "Sourcerer-x86_64.AppImage")],
                              env=dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1"))


def main():
    if len(sys.argv) > 1 and sys.argv[1].startswith("-"):
        sys.exit(__doc__)
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "build-exe").resolve()
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    assets = out / "assets"
    assets.mkdir()
    version = (FILES / "VERSION").read_text(encoding="utf-8").strip()
    {"win32": windows, "darwin": macos}.get(sys.platform, linux)(out, assets, version)
    for p in sorted(assets.iterdir()):
        print("built %s (v%s, %.1f MB)" % (p, version, size_mb(p)))


if __name__ == "__main__":
    main()
