from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


def test_windows_package_zip_keeps_executable_dlls_resources_and_hidden_files(tmp_path) -> None:
    repository = Path(__file__).resolve().parents[2]
    package_dir = tmp_path / "dist" / "PickList"
    (package_dir / "_internal" / "PySide6" / "plugins" / "platforms").mkdir(parents=True)
    (package_dir / "PickList.exe").write_bytes(b"exe")
    (package_dir / "_internal" / "PySide6" / "plugins" / "platforms" / "qwindows.dll").write_bytes(b"plugin")
    (package_dir / "assets").mkdir()
    (package_dir / "assets" / "pick_list.png").write_bytes(b"png")
    (package_dir / ".hidden-resource").write_bytes(b"hidden")
    zip_path = tmp_path / "Pick-List-Windows-x64.zip"

    subprocess.run(
        [
            sys.executable,
            str(repository / "scripts" / "package-pyinstaller-windows.py"),
            str(package_dir),
            str(zip_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    with ZipFile(zip_path) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "PickList/PickList.exe",
            "PickList/_internal/PySide6/plugins/platforms/qwindows.dll",
            "PickList/assets/pick_list.png",
            "PickList/.hidden-resource",
        }
