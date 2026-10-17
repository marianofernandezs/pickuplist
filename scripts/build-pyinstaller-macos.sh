#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
BACKEND="$ROOT/backend"
PYTHON_VERSION="3.12.13"
APP_IDENTIFIER="com.picklist.desktop"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Error: macOS bundles must be built on macOS." >&2
  exit 1
fi

EXPECTED_ARCH="${1:-}"
CHECK_ONLY=0
if [[ "${2:-}" == "--check-only" && "$#" -eq 2 ]]; then
  CHECK_ONLY=1
elif [[ "$#" -gt 1 ]]; then
  echo "Usage: $0 <arm64|x86_64> [--check-only]" >&2
  exit 2
fi
case "$EXPECTED_ARCH" in
  arm64|x86_64) ;;
  *)
    echo "Usage: $0 <arm64|x86_64> [--check-only]" >&2
    exit 2
    ;;
esac

HOST_ARCH="$(uname -m)"
if [[ "$HOST_ARCH" != "$EXPECTED_ARCH" ]]; then
  echo "Error: refusing cross-architecture build (runner=$HOST_ARCH, requested=$EXPECTED_ARCH)." >&2
  exit 1
fi

resolve_python() {
  local candidate="$1"
  local variable_name="$2"

  if [[ "$candidate" != /* ]]; then
    candidate="$ROOT/$candidate"
  fi
  if [[ ! -x "$candidate" ]]; then
    echo "Error: $variable_name does not point to an executable Python: $candidate" >&2
    return 1
  fi
  printf '%s' "$candidate"
}

APP_PYTHON="$(resolve_python "${PICK_LIST_APP_PYTHON:-$BACKEND/.venv/bin/python}" PICK_LIST_APP_PYTHON)"
PACKAGER_PYTHON="$(resolve_python "${PICK_LIST_PACKAGER_PYTHON:-$APP_PYTHON}" PICK_LIST_PACKAGER_PYTHON)"
APP_SITE_PACKAGES="$("$APP_PYTHON" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
if [[ ! -d "$APP_SITE_PACKAGES" ]]; then
  echo "Error: application Python site-packages directory does not exist: $APP_SITE_PACKAGES" >&2
  exit 1
fi

# Make application dependencies visible to PyInstaller's analysis even when
# PyInstaller itself runs from a separate, build-only Python environment.
if [[ -n "${PYTHONPATH:-}" ]]; then
  export PYTHONPATH="$BACKEND:$APP_SITE_PACKAGES:$PYTHONPATH"
else
  export PYTHONPATH="$BACKEND:$APP_SITE_PACKAGES"
fi
export PYTHONNOUSERSITE=1

SPEC="$ROOT/scripts/pyinstaller/PickList.spec"
VALIDATOR="$ROOT/scripts/validate-pyinstaller-macos.py"
for required_path in "$SPEC" "$VALIDATOR"; do
  if [[ ! -f "$required_path" ]]; then
    echo "Error: required packaging file is missing: $required_path" >&2
    exit 1
  fi
done
for required_command in lipo codesign ditto; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "Error: required macOS packaging command is unavailable: $required_command" >&2
    exit 1
  fi
done

echo "Checking application and packager environments..."
"$APP_PYTHON" - "$EXPECTED_ARCH" "$APP_SITE_PACKAGES" <<'PY'
import importlib
import platform
import sys
from pathlib import Path

expected_arch, site_packages = sys.argv[1:]
if platform.python_version() != "3.12.13":
    raise SystemExit(f"Application Python must be 3.12.13, got {platform.python_version()}")
if platform.python_implementation() != "CPython":
    raise SystemExit(f"Application interpreter must be CPython, got {platform.python_implementation()}")
if platform.machine() != expected_arch:
    raise SystemExit(f"Application Python architecture mismatch: expected {expected_arch}, got {platform.machine()}")

modules = {
    "PySide6": "6.12.0",
    "pymupdf": "1.28.2",
    "pdfplumber": None,
    "pdfminer": None,
    "reportlab": None,
}
for name, expected_version in modules.items():
    module = importlib.import_module(name)
    module_path = Path(module.__file__).resolve()
    if Path(site_packages).resolve() not in module_path.parents:
        raise SystemExit(f"{name} did not load from the selected application environment: {module_path}")
    if name == "PySide6":
        version = module.__version__
    elif name == "pymupdf":
        version = module.VersionBind
    else:
        version = None
    if expected_version is not None and version != expected_version:
        raise SystemExit(f"{name} must be {expected_version}, got {version}")
    print(f"Application module available: {name}" + (f" {version}" if version else ""))

print(f"Application Python: {platform.python_version()} ({platform.machine()})")
PY

"$PACKAGER_PYTHON" - "$EXPECTED_ARCH" "$APP_SITE_PACKAGES" <<'PY'
import importlib
import platform
import sys
from pathlib import Path

import PyInstaller

expected_arch, site_packages = sys.argv[1:]
if platform.python_version() != "3.12.13":
    raise SystemExit(f"Packager Python must be 3.12.13, got {platform.python_version()}")
if platform.python_implementation() != "CPython":
    raise SystemExit(f"Packager interpreter must be CPython, got {platform.python_implementation()}")
if platform.machine() != expected_arch:
    raise SystemExit(f"Packager Python architecture mismatch: expected {expected_arch}, got {platform.machine()}")
if PyInstaller.__version__ != "6.22.3":
    raise SystemExit(f"PyInstaller must be 6.22.3, got {PyInstaller.__version__}")

from PyInstaller.utils.hooks import collect_all

for name in ("PySide6", "pymupdf", "fitz", "pdfplumber", "pdfminer", "reportlab"):
    module = importlib.import_module(name)
    module_path = Path(module.__file__).resolve()
    if Path(site_packages).resolve() not in module_path.parents:
        raise SystemExit(f"PyInstaller analysis found {name} outside the selected application environment: {module_path}")
    print(f"PyInstaller analysis can collect: {name}")

for name in ("pymupdf", "fitz", "pdfplumber", "pdfminer", "reportlab"):
    collect_all(name)

print(f"PyInstaller: {PyInstaller.__version__}")
print(f"Packager Python: {platform.python_version()} ({platform.machine()})")
PY

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  echo "Preflight checks passed; build skipped by --check-only."
  exit 0
fi

OUTPUT_ROOT="${PICK_LIST_PYINSTALLER_OUTPUT_ROOT:-$ROOT/dist/macos/pyinstaller/$EXPECTED_ARCH}"
if [[ "$OUTPUT_ROOT" != /* ]]; then
  OUTPUT_ROOT="$ROOT/$OUTPUT_ROOT"
fi
mkdir -p "$OUTPUT_ROOT"
OUTPUT_ROOT="$(cd "$OUTPUT_ROOT" && pwd -P)"
RUN_ID="$(date '+%Y%m%d-%H%M%S')-$$"
RUN_DIR="$OUTPUT_ROOT/run-$RUN_ID"
if ! mkdir "$RUN_DIR"; then
  echo "Error: refusing to reuse existing build directory: $RUN_DIR" >&2
  exit 1
fi

DIST_DIR="$RUN_DIR/dist"
WORK_DIR="$RUN_DIR/work"
PYINSTALLER_CONFIG_DIR="$RUN_DIR/pyinstaller-config"
LOG_FILE="$RUN_DIR/build.log"
ARCHIVE="$RUN_DIR/Pick-List-macOS-$EXPECTED_ARCH.zip"
APP="$DIST_DIR/Pick List.app"
SPEC="$ROOT/scripts/pyinstaller/PickList.spec"
mkdir -p "$DIST_DIR" "$WORK_DIR" "$PYINSTALLER_CONFIG_DIR"
if [[ -e "$LOG_FILE" || -e "$ARCHIVE" || -e "$APP" ]]; then
  echo "Error: build output already exists under $RUN_DIR; refusing to overwrite it." >&2
  exit 1
fi

export PICK_LIST_TARGET_ARCH="$EXPECTED_ARCH"
export PYINSTALLER_CONFIG_DIR

{
  echo "Build: PyInstaller onedir/windowed macOS bundle"
  echo "Repository: $ROOT"
  echo "Host architecture: $HOST_ARCH"
  echo "Target architecture: $EXPECTED_ARCH"
  echo "Python: $PYTHON_VERSION"
  echo "Application Python: $APP_PYTHON"
  echo "Packager Python: $PACKAGER_PYTHON"
  echo "Application site-packages: $APP_SITE_PACKAGES"
  echo "Bundle identifier: $APP_IDENTIFIER"
  echo "Build workspace: $RUN_DIR"
  echo "Log: $LOG_FILE"

  "$PACKAGER_PYTHON" -m PyInstaller --noconfirm --clean \
    --distpath "$DIST_DIR" --workpath "$WORK_DIR" "$SPEC"

  if [[ ! -d "$APP" ]]; then
    echo "Error: PyInstaller did not produce the expected app: $APP" >&2
    exit 1
  fi

  "$APP_PYTHON" "$VALIDATOR" --app "$APP" --arch "$EXPECTED_ARCH"
  ditto -c -k --keepParent "$APP" "$ARCHIVE"
  "$APP_PYTHON" "$VALIDATOR" --app "$APP" --arch "$EXPECTED_ARCH" --archive "$ARCHIVE"
  du -sh "$APP" "$ARCHIVE"
  echo "Artifact: $ARCHIVE"
} 2>&1 | tee "$LOG_FILE"
