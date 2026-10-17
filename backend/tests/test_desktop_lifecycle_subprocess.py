from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


_CHILD = r'''
import atexit
import os
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from app.desktop.application import LocalSource, ProcessedBatch, SessionProduct
import app.desktop.main as desktop_main

scenario = os.environ["PICK_LIST_LIFECYCLE_SCENARIO"]
gate = threading.Event()

def report_python_finalization():
    print("python-finalization", flush=True)

atexit.register(report_python_finalization)

class ProbeApplication(QApplication):
    def exec(self):
        result = super().exec()
        print(f"event-loop-exit {result}", flush=True)
        return result

class ProbeWindow(desktop_main.MainWindow):
    def __init__(self):
        super().__init__()
        if scenario == "populated":
            self.session.sources.append(LocalSource("sample.pdf", 1, False, "processed"))
            self.session.products.append(SessionProduct("ARROZ", "caja", 4, "caja"))
            self.refresh_all()

    def show(self):
        super().show()
        if scenario in ("worker_active_cancel", "worker_completed"):
            QTimer.singleShot(0, self.start_worker)
        else:
            QTimer.singleShot(0, self.close)

    def start_worker(self):
        def select_pdf(*_args):
            return (["sample.pdf"], "")

        QFileDialog.getOpenFileNames = select_pdf

        def process_files(_paths, progress=None, cancel_event=None):
            if progress is not None:
                progress(0, 1)
            gate.wait()
            if scenario == "worker_active_cancel" and cancel_event is not None and cancel_event.is_set():
                return None
            return ProcessedBatch(
                (LocalSource("sample.pdf", 1, False, "processed"),),
                (SessionProduct("ARROZ", "caja", 4, "caja"),),
                (),
            )

        desktop_main.process_files = process_files
        self.choose_files()
        if scenario == "worker_completed":
            gate.set()

    def on_progress(self, completed, total):
        super().on_progress(completed, total)
        if scenario == "worker_active_cancel":
            self.close()
            self.close()  # Repeated close during cooperative cancellation is safe.
            gate.set()

    def on_processed(self, sources, error):
        super().on_processed(sources, error)
        if scenario == "worker_active_cancel":
            assert not self.session.sources
            assert not self.session.products
        elif scenario == "worker_completed":
            assert [source.filename for source in self.session.sources] == ["sample.pdf"]
            assert [product.description_exact for product in self.session.products] == ["ARROZ"]

    def _finish_processing_if_ready(self):
        super()._finish_processing_if_ready()
        if scenario == "worker_completed" and self._worker_thread is None:
            self.close()

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            print("closeEvent-accepted", flush=True)
        else:
            print("closeEvent-deferred", flush=True)

desktop_main.MainWindow = ProbeWindow
desktop_main.QApplication = ProbeApplication
result = desktop_main.main()
print(f"main-return {result}", flush=True)
'''


@pytest.mark.parametrize(
    "scenario",
    ["empty", "populated", "worker_active_cancel", "worker_completed"],
)
def test_qt_application_finalizes_cleanly_in_a_subprocess(scenario: str) -> None:
    backend = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PICK_LIST_LIFECYCLE_SCENARIO"] = scenario
    python_path = str(backend)
    if env.get("PYTHONPATH"):
        python_path += os.pathsep + env["PYTHONPATH"]
    env["PYTHONPATH"] = python_path

    result = subprocess.run(
        [sys.executable, "-c", _CHILD],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, f"{scenario} process exited {result.returncode}:\n{output}"
    assert "closeEvent-accepted" in result.stdout, output
    assert "event-loop-exit 0" in result.stdout, output
    assert "main-return 0" in result.stdout, output
    assert "python-finalization" in result.stdout, output
    if scenario == "worker_active_cancel":
        assert "closeEvent-deferred" in result.stdout, output
