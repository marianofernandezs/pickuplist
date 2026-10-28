# -*- mode: python ; coding: utf-8 -*-
"""Windows x64 onedir/windowed bundle for Pick List Desktop."""

import platform
import struct
import sys
from pathlib import Path

import PyInstaller
import PySide6
import fitz
from PyInstaller.utils.hooks import collect_all


if sys.platform != "win32":
    raise SystemExit("PickList-windows.spec must be built on Windows.")
if struct.calcsize("P") != 8 or platform.machine().upper() not in {"AMD64", "X86_64"}:
    raise SystemExit("PickList Windows builds require a native x64 Python runner.")
if platform.python_version() != "3.12.13":
    raise SystemExit(f"Expected Python 3.12.13, got {platform.python_version()}")
if PyInstaller.__version__ != "6.22.3":
    raise SystemExit(f"Expected PyInstaller 6.22.3, got {PyInstaller.__version__}")
if PySide6.__version__ != "6.12.0":
    raise SystemExit(f"Expected PySide6 6.12.0, got {PySide6.__version__}")
if fitz.VersionBind != "1.28.2":
    raise SystemExit(f"Expected PyMuPDF 1.28.2, got {fitz.VersionBind}")

REPOSITORY_ROOT = Path(SPECPATH).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
ICON_ROOT = BACKEND_ROOT / "app" / "desktop" / "assets" / "icons"
PNG_ICON = ICON_ROOT / "pick_list.png"
WINDOWS_ICON = ICON_ROOT / "PickList.ico"

if not PNG_ICON.is_file():
    raise SystemExit(f"Missing original PNG resource: {PNG_ICON}")
if not WINDOWS_ICON.is_file():
    raise SystemExit(f"Missing Windows executable icon: {WINDOWS_ICON}")

datas = [(str(PNG_ICON), "assets/icons")]
binaries = []
hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPrintSupport",
]
for package in ("pymupdf", "fitz", "pdfplumber", "pdfminer", "reportlab"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

analysis = Analysis(
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
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PickList",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(WINDOWS_ICON),
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PickList",
)
