# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller macOS onedir/windowed bundle for Pick List Desktop."""

import os
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


TARGET_ARCH = os.environ.get("PICK_LIST_TARGET_ARCH", "")
EXPECTED_HOST_ARCH = {"arm64": "arm64", "x86_64": "x86_64"}
if TARGET_ARCH not in EXPECTED_HOST_ARCH:
    raise SystemExit("PICK_LIST_TARGET_ARCH must be arm64 or x86_64")
if platform.machine() != EXPECTED_HOST_ARCH[TARGET_ARCH]:
    raise SystemExit(
        f"Refusing cross-architecture build: requested {TARGET_ARCH}, "
        f"Python reports {platform.machine()}"
    )

REPOSITORY_ROOT = Path(SPECPATH).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

datas = []
binaries = []
hiddenimports = []
for package in ("pymupdf", "fitz", "pdfplumber", "pdfminer", "reportlab"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    [str(BACKEND_ROOT / "app" / "desktop" / "main.py")],
    pathex=[str(BACKEND_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PickList",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PickList",
)
app = BUNDLE(
    coll,
    name="Pick List.app",
    icon=None,
    bundle_identifier="com.picklist.desktop",
    info_plist={"CFBundleName": "Pick List", "CFBundleDisplayName": "Pick List"},
)
