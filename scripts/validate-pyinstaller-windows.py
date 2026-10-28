#!/usr/bin/env python3
"""Validate a Windows x64 Pick List PyInstaller onedir package and smoke-test it."""

from __future__ import annotations

import argparse
import ctypes
import os
import struct
import subprocess
import sys
from pathlib import Path


EXPECTED_MACHINE = 0x8664  # IMAGE_FILE_MACHINE_AMD64
SMOKE_TIMEOUT_SECONDS = 45


def fail(message: str) -> None:
    raise SystemExit(f"Windows package validation failed: {message}")


def pe_metadata(executable: Path) -> tuple[int, int]:
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            fail(f"not a Windows executable: {executable}")
        stream.seek(0x3C)
        pe_offset_bytes = stream.read(4)
        if len(pe_offset_bytes) != 4:
            fail("truncated DOS header")
        pe_offset = struct.unpack("<I", pe_offset_bytes)[0]
        stream.seek(pe_offset)
        if stream.read(4) != b"PE\0\0":
            fail("missing PE signature")
        machine_bytes = stream.read(2)
        if len(machine_bytes) != 2:
            fail("truncated PE header")
        machine = struct.unpack("<H", machine_bytes)[0]
        stream.seek(pe_offset + 24)
        optional_magic_bytes = stream.read(2)
        if len(optional_magic_bytes) != 2:
            fail("truncated PE optional header")
        optional_magic = struct.unpack("<H", optional_magic_bytes)[0]
        if optional_magic not in (0x10B, 0x20B):
            fail("unsupported PE optional header")
        stream.seek(pe_offset + 24 + 68)
        subsystem_bytes = stream.read(2)
        if len(subsystem_bytes) != 2:
            fail("truncated PE subsystem field")
        subsystem = struct.unpack("<H", subsystem_bytes)[0]
        return machine, subsystem


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--icon", type=Path, required=True)
    args = parser.parse_args()

    if sys.platform != "win32":
        fail("the frozen executable smoke test must run on Windows")
    package_dir = args.dist_dir.resolve() / "PickList"
    executable = package_dir / "PickList.exe"
    if not executable.is_file():
        fail(f"missing executable: {executable}")
    machine, subsystem = pe_metadata(executable)
    if machine != EXPECTED_MACHINE:
        fail("executable is not Windows x64 (AMD64)")
    if subsystem != 2:  # IMAGE_SUBSYSTEM_WINDOWS_GUI
        fail("executable is not configured as a windowed GUI application")

    icon_data = args.icon.read_bytes()
    if len(icon_data) < 6 or icon_data[:4] != b"\0\0\1\0":
        fail(f"invalid ICO resource: {args.icon}")
    icon_count = struct.unpack_from("<H", icon_data, 4)[0]
    if icon_count < 1:
        fail("ICO contains no image variants")
    extract_icons = ctypes.windll.shell32.ExtractIconExW
    extract_icons.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint,
    ]
    extract_icons.restype = ctypes.c_uint
    extract_icon_count = extract_icons(str(executable), -1, None, None, 0)
    if extract_icon_count < 1:
        fail("executable does not contain an embedded Windows icon")

    files = [path for path in package_dir.rglob("*") if path.is_file()]
    names = {path.name.lower() for path in files}
    if "qwindows.dll" not in names:
        fail("Qt Windows platform plugin qwindows.dll is missing")
    for module in ("qtpdf.pyd", "qtprintsupport.pyd"):
        if module not in names:
            fail(f"Qt module is missing: {module}")
    if not any(path.name.lower() == "pick_list.png" for path in files):
        fail("original pick_list.png resource is missing")

    smoke_env = os.environ.copy()
    smoke_env.pop("QT_QPA_PLATFORM", None)
    try:
        result = subprocess.run(
            [str(executable), "--smoke-test"],
            cwd=package_dir,
            env=smoke_env,
            capture_output=True,
            text=True,
            timeout=SMOKE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        fail(f"startup smoke test exceeded {SMOKE_TIMEOUT_SECONDS}s: {exc}")
    if result.returncode != 0:
        fail(
            "startup smoke test failed with exit code "
            f"{result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
        )

    print(f"Windows x64 executable: {executable}")
    print(f"ICO source variants: {icon_count}; executable icon resources: {extract_icon_count}")
    print("Qt qwindows.dll, QtPdf, QtPrintSupport, and PNG resource: present")
    print(f"Frozen startup smoke test: passed ({SMOKE_TIMEOUT_SECONDS}s timeout)")


if __name__ == "__main__":
    main()
