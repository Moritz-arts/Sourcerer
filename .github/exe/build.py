"""Build the standalone Sourcerer (PyInstaller) for the system this runs on, and package it.

    python .github/exe/build.py [out_dir]     (needs: pip install -r Sourcerer_files/requirements.txt pyinstaller)

Everything to publish ends up in <out_dir>/assets/:

    Windows   Sourcerer-Setup.exe             the installer (Inno Setup; per user, no admin)
              Sourcerer-Windows.zip           portable: Sourcerer.exe + Sourcerer_files/
    macOS     Sourcerer-macOS-<arch>.dmg      the app, to drag into Applications
    Linux     Sourcerer-x86_64.AppImage       one file
              Sourcerer-Linux.tar.gz          portable: Sourcerer/ with the binary + Sourcerer_files/

Windows and Linux bundles are Sourcerer(.exe) plus ONE folder, Sourcerer_files/
(PyInstaller's --contents-directory): the repository's folder name, so config.ROOT, the static
files, VERSION and Userdata/ sit where the program already looks for them. The macOS app is
the usual bundle; there (and in an AppImage) Userdata lives in the user's data folder, see
config.py.
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


def freeze(out):
    sep = os.pathsep
    args = [
        str(FILES / "app.py"), "--noconfirm", "--clean",
        "--name", "Sourcerer", "--windowed",
        "--distpath", str(out / "dist"), "--workpath", str(out / "work"), "--specpath", str(out),
        "--paths", str(FILES),
        "--add-data", "%s%sstatic" % (FILES / "static", sep),
        "--add-data", "%s%s." % (FILES / "VERSION", sep),
        # gallery-dl loads its extractors by name at run time, which no import scan sees.
        "--collect-submodules", "gallery_dl", "--copy-metadata", "gallery-dl",
    ]
    if sys.platform == "darwin":
        args += ["--icon", str(HERE / "Sourcerer.icns"), "--osx-bundle-identifier", "io.github.moritz-arts.sourcerer"]
    else:
        args += ["--contents-directory", "Sourcerer_files"]
    if sys.platform == "win32":
        args += ["--icon", str(HERE / "Sourcerer.ico")]
    if sys.platform in ("win32", "darwin"):
        # The window: pywebview on WebView2 (through pythonnet) or WKWebView; their libraries are
        # found by hooks only when asked for. Without them Sourcerer still starts, in the browser.
        # Linux has no such bridge in the bundle (GTK/Qt come from the system): browser only.
        for pkg in ("webview",) + (("pythonnet", "clr_loader") if sys.platform == "win32" else ()):
            args += ["--collect-all", pkg]
    PyInstaller.__main__.run(args)
    return out / "dist"


def write_zip(path, root):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(root).as_posix())


def windows(dist, assets, version):
    bundle = dist / "Sourcerer"
    write_zip(assets / "Sourcerer-Windows.zip", bundle)
    iscc = shutil.which("iscc") or next((str(p) for p in (
        pathlib.Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        pathlib.Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe") if p.is_file()), None)
    if not iscc:
        sys.exit("Inno Setup (ISCC.exe) not found -- choco install innosetup")
    subprocess.check_call([iscc, "/Qp", "/DVersion=" + version, "/DSourceDir=" + str(bundle),
                           "/DOutputDir=" + str(assets), "/DIcon=" + str(HERE / "Sourcerer.ico"),
                           str(HERE / "Sourcerer.iss")])


def macos(dist, assets, version):
    arch = "arm64" if platform.machine() == "arm64" else "x86_64"
    with tempfile.TemporaryDirectory() as tmp:
        stage = pathlib.Path(tmp) / "Sourcerer"
        stage.mkdir()
        # symlinks=True: a bundle's frameworks are links; copying them as files breaks the signature.
        shutil.copytree(dist / "Sourcerer.app", stage / "Sourcerer.app", symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        subprocess.check_call(["hdiutil", "create", "-volname", "Sourcerer", "-srcfolder", str(stage),
                               "-ov", "-format", "UDZO", str(assets / ("Sourcerer-macOS-%s.dmg" % arch))])


def linux(dist, assets, version):
    bundle = dist / "Sourcerer"
    with tarfile.open(assets / "Sourcerer-Linux.tar.gz", "w:gz") as t:
        t.add(bundle, arcname="Sourcerer")          # keeps the executable bits
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
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "build-exe").resolve()
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    assets = out / "assets"
    assets.mkdir()
    version = (FILES / "VERSION").read_text(encoding="utf-8").strip()
    dist = freeze(out)
    if sys.platform != "darwin":
        assert (dist / "Sourcerer" / "Sourcerer_files" / "VERSION").read_text(encoding="utf-8").strip() == version
    {"win32": windows, "darwin": macos}.get(sys.platform, linux)(dist, assets, version)
    for p in sorted(assets.iterdir()):
        print("built %s (v%s, %.1f MB)" % (p, version, p.stat().st_size / 1e6))


if __name__ == "__main__":
    main()
