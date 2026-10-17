"""Timeout-protected subprocess check for the PyMuPDF/Nuitka probe.

Set PICK_LIST_PYMUPDF_PROBE_EXECUTABLE to a standalone compiled probe to run
the same assertions against that binary without requiring Python in the child.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROBE_SCRIPT = BACKEND_ROOT / "scripts" / "pymupdf_get_text_probe.py"
PROBE_TIMEOUT_SECONDS = 30


def test_pymupdf_text_path_finishes_in_a_subprocess() -> None:
    compiled_probe = os.environ.get("PICK_LIST_PYMUPDF_PROBE_EXECUTABLE")
    command = [compiled_probe] if compiled_probe else [sys.executable, str(PROBE_SCRIPT)]

    try:
        completed = subprocess.run(
            command,
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        pytest.fail(
            f"PyMuPDF probe exceeded {PROBE_TIMEOUT_SECONDS}s; possible hang.\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )

    assert completed.returncode == 0, (
        f"PyMuPDF probe exited with status {completed.returncode}; "
        f"negative status indicates signal {-completed.returncode}.\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "[probe] page 1 direct get_text('text'): done" in completed.stdout
    assert "[probe] page 1 direct get_text('words'): done" in completed.stdout
    assert "[probe] extract_document_summary (text + words APIs): done" in completed.stdout
    assert "[probe] page 1 Rect(cropbox) / util_make_rect: done" in completed.stdout
    assert "[probe] completed" in completed.stdout
