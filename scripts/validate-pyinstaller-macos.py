#!/usr/bin/env python3
"""Validate a PyInstaller macOS app bundle and its ditto ZIP artifact."""

from __future__ import annotations

import argparse
import os
import plistlib
import stat
import subprocess
import sys
import zipfile
from pathlib import Path


BUNDLE_IDENTIFIER = "com.picklist.desktop"
APP_NAME = "Pick List.app"
EXECUTABLE_NAME = "PickList"


def fail(message: str) -> None:
    raise SystemExit(f"Bundle validation failed: {message}")


def command_output(*args: str) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout + result.stderr


def validate_bundle(app: Path, expected_arch: str) -> dict[str, str]:
    app = app.resolve(strict=True)
    if app.name != APP_NAME or not app.is_dir():
        fail(f"expected a directory named {APP_NAME}: {app}")

    contents = app / "Contents"
    plist_path = contents / "Info.plist"
    executable = contents / "MacOS" / EXECUTABLE_NAME
    for required in (contents / "MacOS", contents / "Frameworks", contents / "Resources"):
        if not required.is_dir():
            fail(f"missing bundle directory: {required.relative_to(app)}")
    if not plist_path.is_file() or not executable.is_file():
        fail("Info.plist or CFBundleExecutable is missing")
    if not executable.stat().st_mode & stat.S_IXUSR:
        fail("bundle executable is not executable")

    with plist_path.open("rb") as plist_file:
        info = plistlib.load(plist_file)
    if info.get("CFBundleExecutable") != EXECUTABLE_NAME:
        fail("CFBundleExecutable does not match the PickList executable")
    if info.get("CFBundleIdentifier") != BUNDLE_IDENTIFIER:
        fail("CFBundleIdentifier is not the stable com.picklist.desktop identifier")
    if info.get("CFBundlePackageType") != "APPL":
        fail("CFBundlePackageType is not APPL")

    architectures = command_output("lipo", "-archs", str(executable)).split()
    if set(architectures) != {expected_arch}:
        fail(f"expected only {expected_arch}, found {architectures}")

    symlinks: dict[str, str] = {}
    for path in app.rglob("*"):
        if path.is_symlink():
            try:
                path.resolve(strict=True)
            except (OSError, RuntimeError) as error:
                fail(f"broken or cyclic symlink {path.relative_to(app)}: {error}")
            symlinks[f"{APP_NAME}/{path.relative_to(app).as_posix()}"] = os.readlink(path)

    qt_cocoa_plugin = [
        path for path in app.rglob("libqcocoa.dylib") if path.is_file()
    ]
    if not qt_cocoa_plugin:
        fail("Qt Cocoa platform plugin (libqcocoa.dylib) is missing")
    mupdf_libraries = [
        path for path in app.rglob("libmupdf*") if path.is_file()
    ]
    if not mupdf_libraries:
        fail("PyMuPDF/MuPDF native libraries are missing")

    command_output("codesign", "--verify", "--deep", "--strict", str(app))
    signature = command_output("codesign", "-dv", "--verbose=4", str(app))
    if "Signature=adhoc" not in signature and "(adhoc)" not in signature:
        fail("bundle is not ad hoc signed (Developer ID signing is not expected here)")

    print(f"Validated app: {app}")
    print(f"Architecture: {expected_arch}")
    print(f"Bundle identifier: {BUNDLE_IDENTIFIER}")
    print(f"Qt Cocoa plugin: {qt_cocoa_plugin[0].relative_to(app)}")
    print(f"PyMuPDF native library: {mupdf_libraries[0].relative_to(app)}")
    print("Code signature: valid ad hoc signature")
    return symlinks


def validate_archive(
    archive: Path, expected_arch: str, expected_symlinks: dict[str, str]
) -> None:
    with zipfile.ZipFile(archive) as zipped:
        names = set(zipped.namelist())
        executable_name = f"{APP_NAME}/Contents/MacOS/{EXECUTABLE_NAME}"
        if executable_name not in names:
            fail(f"ZIP is missing {executable_name}")
        executable_info = zipped.getinfo(executable_name)
        executable_mode = executable_info.external_attr >> 16
        if not executable_mode & stat.S_IXUSR:
            fail("ZIP did not preserve the executable permission")

        symlink_infos = {
            item.filename: zipped.read(item).decode("utf-8")
            for item in zipped.infolist()
            if stat.S_ISLNK(item.external_attr >> 16)
        }
        if symlink_infos != expected_symlinks:
            fail(
                "ZIP did not preserve bundle symlink names and targets "
                f"(expected {len(expected_symlinks)}, found {len(symlink_infos)})"
            )
        if not any(
            name.startswith(f"{APP_NAME}/Contents/Frameworks/") for name in names
        ):
            fail("ZIP is missing the bundled Frameworks directory")

    print(f"Validated ZIP: {archive}")
    print(f"ZIP architecture source: {expected_arch}")
    print(f"Preserved symlinks and targets: {len(expected_symlinks)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--arch", required=True, choices=("arm64", "x86_64"))
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()

    symlinks = validate_bundle(args.app, args.arch)
    if args.archive is not None:
        if not args.archive.is_file():
            fail(f"ZIP artifact is missing: {args.archive}")
        validate_archive(args.archive, args.arch, symlinks)


if __name__ == "__main__":
    main()
