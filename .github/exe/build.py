"""Build the standalone Sourcerer (PyInstaller) and zip it as Sourcerer-Windows.zip.

    python .github/exe/build.py [out_dir]        (needs: pip install -r Sourcerer_files/requirements.txt pyinstaller)

The bundle is Sourcerer.exe plus ONE folder, Sourcerer_files/ (PyInstaller's
--contents-directory): the same name as the repository's, so config.ROOT, the
static files, VERSION and Userdata/ sit where the program already looks for them.
The zip therefore unpacks to the same shape as Sourcerer.zip: no wrapper folder,
and copying a new Sourcerer.exe + Sourcerer_files over the old ones keeps Userdata/.

Runs on Linux too (a test build, no icon) -- the paths and the frozen start can
be checked there; the window and WebView2 only on Windows.
"""
import os
import pathlib
import shutil
import sys
import zipfile

import PyInstaller.__main__

REPO = pathlib.Path(__file__).resolve().parents[2]
FILES = REPO / "Sourcerer_files"
ICON = pathlib.Path(__file__).resolve().parent / "Sourcerer.ico"
ASSET = "Sourcerer-Windows.zip"


def main():
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "build-exe").resolve()
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    sep = os.pathsep
    args = [
        str(FILES / "app.py"), "--noconfirm", "--clean",
        "--name", "Sourcerer", "--windowed", "--contents-directory", "Sourcerer_files",
        "--distpath", str(out / "dist"), "--workpath", str(out / "work"), "--specpath", str(out),
        "--paths", str(FILES),
        "--add-data", "%s%sstatic" % (FILES / "static", sep),
        "--add-data", "%s%s." % (FILES / "VERSION", sep),
        # gallery-dl loads its extractors by name at run time, which no import scan sees.
        "--collect-submodules", "gallery_dl", "--copy-metadata", "gallery-dl",
    ]
    if sys.platform == "win32":
        # The window: pywebview on WebView2 through pythonnet; their DLLs are found by hooks only
        # when asked for. Without them Sourcerer still starts, in the browser.
        for pkg in ("webview", "pythonnet", "clr_loader"):
            args += ["--collect-all", pkg]
        args += ["--icon", str(ICON)]
    PyInstaller.__main__.run(args)

    bundle = out / "dist" / "Sourcerer"
    version = (FILES / "VERSION").read_text(encoding="utf-8").strip()
    assert (bundle / "Sourcerer_files" / "VERSION").read_text(encoding="utf-8").strip() == version
    zip_path = out / ASSET
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(bundle).as_posix())
    print("built %s (v%s, %.1f MB)" % (zip_path, version, zip_path.stat().st_size / 1e6))


if __name__ == "__main__":
    main()
