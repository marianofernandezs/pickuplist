#!/usr/bin/env python3
"""Create a complete ZIP of a Windows PyInstaller onedir directory."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("zip_path", type=Path)
    args = parser.parse_args()

    package_dir = args.package_dir.resolve(strict=True)
    zip_path = args.zip_path.resolve(strict=False)
    if not package_dir.is_dir():
        raise SystemExit(f"Package directory does not exist: {package_dir}")
    files = sorted(path for path in package_dir.rglob("*") if path.is_file())
    if not files:
        raise SystemExit(f"Package directory is empty: {package_dir}")
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with ZipFile(zip_path, mode="x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for path in files:
                archive.write(path, path.relative_to(package_dir.parent))
            bad_file = archive.testzip()
            if bad_file is not None:
                raise SystemExit(f"ZIP integrity check failed at {bad_file}")
    except FileExistsError:
        raise SystemExit(f"Refusing to replace an existing ZIP: {zip_path}") from None

    print(f"Created {zip_path} with {len(files)} package files")


if __name__ == "__main__":
    main()
