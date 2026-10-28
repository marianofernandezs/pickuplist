from __future__ import annotations

from pathlib import Path

import fitz
import logging
import re
from threading import get_ident
import pytest
from PIL import Image
from PySide6.QtCore import QEventLoop, QRectF, QThread
from PySide6.QtGui import QImage, QPageLayout, QPageRanges
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog
from PySide6.QtWidgets import QApplication

from app.desktop.application import LocalSource, PickListSession, SessionProduct
from app.desktop import main as desktop_main
from app.desktop.main import MainWindow, PrinterSettings, PrintPdfWorker, PrintSendWorker
from app.services.document_summary import DocumentSummary


REAL_QPRINTER = desktop_main.QPrinter


def _printer_settings() -> PrinterSettings:
    return PrinterSettings(
        printer_name="Mock Printer",
        page_layout=QPageLayout(),
        resolution=72,
        color_mode=REAL_QPRINTER.ColorMode.Color,
        duplex=REAL_QPRINTER.DuplexMode.DuplexNone,
        copy_count=1,
        collate_copies=False,
        page_order=REAL_QPRINTER.PageOrder.FirstPageFirst,
        print_range=REAL_QPRINTER.PrintRange.AllPages,
        from_page=0,
        to_page=0,
        page_ranges=QPageRanges(),
        paper_source=REAL_QPRINTER.PaperSource.Auto,
        full_page=False,
        output_format=REAL_QPRINTER.OutputFormat.NativeFormat,
        output_file_name="",
        font_embedding_enabled=True,
    )


class MockPrinter:
    PrinterMode = REAL_QPRINTER.PrinterMode
    Unit = REAL_QPRINTER.Unit
    PrinterState = REAL_QPRINTER.PrinterState
    PrintRange = REAL_QPRINTER.PrintRange

    def __init__(self, *_args):
        self.created_on_main_thread = QThread.currentThread() == QApplication.instance().thread()
        self.printer_name = "Mock Printer"

    def __getattr__(self, name):
        if name == "moveToThread":
            raise AttributeError("'PySide6.QtPrintSupport.QPrinter' object has no attribute 'moveToThread'")
        if name.startswith("set"):
            return lambda *_args: None
        raise AttributeError(name)

    def isValid(self):
        return True

    def printerName(self):
        return self.printer_name

    def pageLayout(self):
        return QPageLayout()

    def resolution(self):
        return 72

    def colorMode(self):
        return REAL_QPRINTER.ColorMode.Color

    def duplex(self):
        return REAL_QPRINTER.DuplexMode.DuplexNone

    def copyCount(self):
        return 1

    def collateCopies(self):
        return False

    def pageOrder(self):
        return REAL_QPRINTER.PageOrder.FirstPageFirst

    def printRange(self):
        return REAL_QPRINTER.PrintRange.AllPages

    def fromPage(self):
        return 0

    def toPage(self):
        return 0

    def pageRanges(self):
        return QPageRanges()

    def paperSource(self):
        return REAL_QPRINTER.PaperSource.Auto

    def fullPage(self):
        return False

    def outputFormat(self):
        return REAL_QPRINTER.OutputFormat.NativeFormat

    def outputFileName(self):
        return ""

    def fontEmbeddingEnabled(self):
        return True

    def pageRect(self, *_args):
        return QRectF(0, 0, 500, 700)

    def newPage(self):
        return True

    def printerState(self):
        return self.PrinterState.Idle

    def abort(self):
        pass


class MockPrintDialog:
    DialogCode = QPrintDialog.DialogCode
    result = QPrintDialog.DialogCode.Accepted
    instances = []

    def __init__(self, printer, *_args):
        self.printer_id = id(printer)
        self.page_limits = None
        self.print_range = None
        self.instances.append(self)

    def setMinMax(self, minimum, maximum):
        self.page_limits = (minimum, maximum)

    def setPrintRange(self, print_range):
        self.print_range = print_range

    def exec(self):
        return self.result

    def close(self):
        pass

    def deleteLater(self):
        pass


def _session() -> PickListSession:
    return PickListSession(
        sources=[LocalSource("factura.pdf", 1, False, "processed")],
        products=[
            SessionProduct("BOLSA", "caja", 2, "caja"),
            SessionProduct("VASO", "pack", 3, "pack"),
            SessionProduct("LAPIZ", "unitario", 8, "un"),
        ],
        summaries=[DocumentSummary("123", "30 días")],
    )


def _pdf_text(path: Path) -> str:
    with fitz.open(path) as document:
        return " ".join(page.get_text() for page in document)


def _generated_pdf(session: PickListSession, kind: str) -> tuple[Path, object]:
    worker = PrintPdfWorker(session, kind)
    result = []
    worker.finished.connect(lambda *values: result.append(values))
    worker.run()
    path, error, temporary, page_count = result[0]
    assert error is None
    assert path and Path(path).is_file()
    assert page_count > 0
    return Path(path), temporary


def test_print_pdf_generation_matches_export_for_bodega_and_local(tmp_path) -> None:
    session = _session()
    for kind, name in (("bodega", "Lista Pickeo Bodega.pdf"), ("local", "Lista Pickeo Local.pdf")):
        print_path, temporary = _generated_pdf(session, kind)
        export_path = session.export(tmp_path / name, kind)
        assert _pdf_text(print_path) == _pdf_text(export_path)
        if kind == "bodega":
            assert "BOLSA" in _pdf_text(print_path)
            assert "Codigo de facturas escaneadas" in _pdf_text(print_path)
            assert "123" in _pdf_text(print_path)
        else:
            assert "VASO" in _pdf_text(print_path) and "LAPIZ" in _pdf_text(print_path)
            assert "BOLSA" not in _pdf_text(print_path)
        temporary.cleanup()
        assert not print_path.exists()


def test_cancelled_print_dialog_does_not_send_or_report_success(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    MockPrintDialog.instances = []
    monkeypatch.setattr(MockPrintDialog, "result", QPrintDialog.DialogCode.Rejected)
    monkeypatch.setattr(desktop_main, "QPrinter", MockPrinter)
    monkeypatch.setattr(desktop_main, "QPrintDialog", MockPrintDialog)
    monkeypatch.setattr(desktop_main.QPrinterInfo, "availablePrinters", lambda: [object()])
    temporary_directories = []
    real_temp_directory = desktop_main.tempfile.TemporaryDirectory

    def tracked_temp_directory(*args, **kwargs):
        temporary = real_temp_directory(*args, **kwargs)
        temporary_directories.append(temporary)
        return temporary

    monkeypatch.setattr(desktop_main.tempfile, "TemporaryDirectory", tracked_temp_directory)
    messages = []
    monkeypatch.setattr(desktop_main.QMessageBox, "information", lambda *args: messages.append(args))
    window.print_pdf("local")
    qtbot.waitUntil(lambda: not window._printing, timeout=5000)

    assert messages == []
    assert len(MockPrintDialog.instances) == 1
    assert window._print_send_worker is None
    assert temporary_directories and not Path(temporary_directories[0].name).exists()
    window.close()


def test_windows_print_dialog_enables_valid_page_range_and_defaults_to_all(
    qtbot, monkeypatch, tmp_path
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    MockPrintDialog.instances = []
    monkeypatch.setattr(desktop_main, "sys", type("Platform", (), {"platform": "win32"})())
    monkeypatch.setattr(desktop_main, "QPrinter", MockPrinter)
    monkeypatch.setattr(desktop_main, "QPrintDialog", MockPrintDialog)
    monkeypatch.setattr(MockPrintDialog, "result", QPrintDialog.DialogCode.Rejected)
    pdf = tmp_path / "lista con espacios – impresión.pdf"

    assert desktop_main.MainWindow._show_print_dialog_and_send(window, pdf, 4) is False

    dialog = MockPrintDialog.instances[-1]
    assert dialog.page_limits == (1, 4)
    assert dialog.print_range == QAbstractPrintDialog.PrintRange.AllPages
    assert window._print_send_worker is None
    native_test_printer = REAL_QPRINTER()
    qt_dialog = QPrintDialog(native_test_printer)
    qt_dialog.setMinMax(1, 4)
    qt_dialog.setPrintRange(QAbstractPrintDialog.PrintRange.AllPages)
    assert (qt_dialog.minPage(), qt_dialog.maxPage()) == (1, 4)
    assert qt_dialog.testOption(QAbstractPrintDialog.PrintDialogOption.PrintPageRange)
    assert qt_dialog.printer().printRange() == REAL_QPRINTER.PrintRange.AllPages
    qt_dialog.close()
    del qt_dialog, native_test_printer
    window.close()


def test_closing_during_print_waits_for_workers_then_closes(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._printing = True

    window.close()

    assert window.isVisible()
    assert not window.isEnabled()
    assert window._closing

    window._print_result_received = True
    window._print_thread_finished = True
    window._print_send_done = True
    window._print_send_thread_finished = True
    window._finish_print_flow_if_ready()

    assert not window.isVisible()


@pytest.mark.parametrize(
    ("kind", "button_index", "expected_text"),
    [
        ("bodega", 0, "BOLSA"),
        ("local", 1, "VASO"),
    ],
)
def test_print_button_runs_full_threaded_flow_without_moving_printer(
    qtbot, monkeypatch, kind, button_index, expected_text
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.session = _session()
    window.refresh_all()
    MockPrintDialog.instances = []
    monkeypatch.setattr(MockPrintDialog, "result", QPrintDialog.DialogCode.Accepted)

    created_printers = []
    printer_destroyed_on_main = []

    class TrackingPrinter(MockPrinter):
        def __init__(self, *args):
            super().__init__(*args)
            created_printers.append((self.created_on_main_thread, id(self)))

        def __del__(self):
            printer_destroyed_on_main.append(
                QThread.currentThread() == QApplication.instance().thread()
            )

    loaded_pdfs = []
    document_thread_states = []
    painter_thread_states = []

    class Document:
        Error = QPdfDocument.Error
        Status = QPdfDocument.Status

        def __init__(self):
            document_thread_states.append(
                QThread.currentThread() == QApplication.instance().thread()
            )

        def load(self, path):
            loaded_pdfs.append(_pdf_text(Path(path)))
            return QPdfDocument.Error.None_

        def status(self):
            return QPdfDocument.Status.Ready

        def pageCount(self):
            return 1

        def render(self, *_args):
            return QImage(16, 16, QImage.Format.Format_RGB32)

        def close(self):
            document_thread_states.append(
                QThread.currentThread() == QApplication.instance().thread()
            )

    class Painter:
        def __init__(self):
            painter_thread_states.append(
                QThread.currentThread() == QApplication.instance().thread()
            )

        def begin(self, *_args):
            return True

        def drawImage(self, *_args):
            pass

        def end(self):
            return True

    temp_directories = []
    real_temp_directory = desktop_main.tempfile.TemporaryDirectory

    def tracked_temp_directory(*args, **kwargs):
        temporary = real_temp_directory(*args, **kwargs)
        temp_directories.append(temporary)
        return temporary

    success_messages = []
    critical_messages = []
    monkeypatch.setattr(desktop_main.tempfile, "TemporaryDirectory", tracked_temp_directory)
    monkeypatch.setattr(desktop_main, "QPrinter", TrackingPrinter)
    monkeypatch.setattr(desktop_main, "QPrintDialog", MockPrintDialog)
    monkeypatch.setattr(desktop_main, "QPdfDocument", Document)
    monkeypatch.setattr(desktop_main, "QPainter", Painter)
    monkeypatch.setattr(desktop_main.QPrinterInfo, "availablePrinters", lambda: [object()])
    monkeypatch.setattr(
        desktop_main.QMessageBox,
        "information",
        lambda *args: success_messages.append(args),
    )
    monkeypatch.setattr(
        desktop_main.QMessageBox,
        "critical",
        lambda *args: critical_messages.append(args),
    )

    window.print_buttons[button_index].click()
    qtbot.waitUntil(lambda: not window._printing, timeout=5000)

    assert not hasattr(REAL_QPRINTER(), "moveToThread")
    assert not critical_messages
    assert len(success_messages) == 1
    assert len(MockPrintDialog.instances) == 1
    assert MockPrintDialog.instances[0].printer_id == created_printers[0][1]
    assert [created_on_main for created_on_main, _identity in created_printers] == [True, False]
    assert loaded_pdfs and expected_text in loaded_pdfs[0]
    assert document_thread_states == [False, False]
    assert painter_thread_states == [False]
    assert printer_destroyed_on_main == [True, False]
    assert window._print_thread is None
    assert window._print_send_thread is None
    assert window._print_worker is None
    assert window._print_send_worker is None
    assert window._print_thread_finished
    assert window._print_send_thread_finished
    assert temp_directories and not Path(temp_directories[0].name).exists()
    window.close()


@pytest.mark.parametrize(
    ("button_index", "kind", "expected_text"),
    [(0, "bodega", "BOLSA"), (1, "local", "VASO")],
)
def test_print_button_loads_real_exported_pdf_in_send_worker_and_cleans_temp(
    qtbot, monkeypatch, caplog, button_index, kind, expected_text
) -> None:
    """Exercise actual ReportLab export and QPdfDocument.load in the worker thread."""
    caplog.set_level(logging.DEBUG, logger=desktop_main.__name__)
    main_thread_id = get_ident()
    window = MainWindow()
    qtbot.addWidget(window)
    window.session = _session()
    window.refresh_all()
    MockPrintDialog.instances = []
    monkeypatch.setattr(MockPrintDialog, "result", QPrintDialog.DialogCode.Accepted)

    class InterleavingPrintDialog(MockPrintDialog):
        def __init__(self, printer, parent):
            super().__init__(printer, parent)
            self.owner = parent
            self.pdf_exists_after_export_thread_finished = None

        def exec(self):
            # QPrintDialog.exec() runs a nested event loop. Wait for the export
            # QThread's finished signal inside that loop, before accepting the
            # dialog, to reproduce the observed signal interleaving.
            export_thread = self.owner._print_thread
            loop = QEventLoop()
            export_thread.finished.connect(loop.quit)
            if not export_thread.isFinished():
                loop.exec()
            QApplication.processEvents()
            self.export_finished_callback_ran_in_dialog = self.owner._print_thread_finished
            temporary_directory = self.owner._print_temp_dir
            self.pdf_exists_after_export_thread_finished = bool(
                temporary_directory
                and (Path(temporary_directory.name) / f"{kind}.pdf").is_file()
            )
            return self.result

    class TrackingPrinter(MockPrinter):
        def pageRect(self, *_args):
            return QRectF(0, 0, 500, 700)

    class Painter:
        def begin(self, *_args):
            return True

        def drawImage(self, *_args):
            pass

        def end(self):
            return True

    temp_dirs = []
    real_temp_dir = desktop_main.tempfile.TemporaryDirectory

    def tracked_temp_dir(*args, **kwargs):
        temp = real_temp_dir(*args, **kwargs)
        temp_dirs.append(temp)
        return temp

    critical = []
    sent = []
    monkeypatch.setattr(desktop_main.tempfile, "TemporaryDirectory", tracked_temp_dir)
    monkeypatch.setattr(desktop_main, "QPrinter", TrackingPrinter)
    monkeypatch.setattr(desktop_main, "QPrintDialog", InterleavingPrintDialog)
    monkeypatch.setattr(desktop_main, "QPainter", Painter)
    monkeypatch.setattr(desktop_main.QPrinterInfo, "availablePrinters", lambda: [object()])
    monkeypatch.setattr(desktop_main.QMessageBox, "critical", lambda *args: critical.append(args))
    monkeypatch.setattr(desktop_main.QMessageBox, "information", lambda *args: sent.append(args))

    window.print_buttons[button_index].click()
    qtbot.waitUntil(lambda: not window._printing, timeout=5000)

    assert not critical
    assert len(sent) == 1
    assert temp_dirs
    assert not Path(temp_dirs[0].name).exists()
    assert window._print_temp_dir is None
    assert window._print_worker is None
    assert window._print_send_worker is None
    assert window._print_thread is None
    assert window._print_send_thread is None
    dialog = InterleavingPrintDialog.instances[0]
    assert dialog.export_finished_callback_ran_in_dialog is True
    assert dialog.pdf_exists_after_export_thread_finished is True
    assert f"Print PDF after export completed: path=" in caplog.text
    assert "exists=true size_bytes=" in caplog.text
    assert "Print PDF immediately before QPdfDocument.load: path=" in caplog.text
    assert "QPdfDocument loaded print PDF:" in caplog.text
    assert "Removed print temporary directory:" in caplog.text
    assert "exists=False" in caplog.text
    export_log = re.search(
        r"Print PDF after export completed: path=(\S+) exists=true size_bytes=(\d+) thread_id=(\d+)",
        caplog.text,
    )
    load_log = re.search(
        r"Print PDF immediately before QPdfDocument.load: path=(\S+) exists=true size_bytes=(\d+) thread_id=(\d+)",
        caplog.text,
    )
    loaded_log = re.search(
        r"QPdfDocument loaded print PDF: path=(\S+) page_count=(\d+) thread_id=(\d+)",
        caplog.text,
    )
    assert export_log and load_log and loaded_log
    assert Path(export_log.group(1)).is_absolute()
    assert export_log.group(1) == load_log.group(1) == loaded_log.group(1)
    assert int(export_log.group(2)) > 0
    assert export_log.group(2) == load_log.group(2)
    assert int(loaded_log.group(2)) > 0
    assert int(load_log.group(3)) != main_thread_id
    # The real QPdfDocument load and render must succeed for the mocked printer
    # to receive a successful completion from this production worker flow.
    assert expected_text in _pdf_text_from_log_free_export(window.session, kind)
    window.close()


def _pdf_text_from_log_free_export(session: PickListSession, kind: str) -> str:
    """Read expected business content from the unchanged exporter, outside logs."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="pick-list-test-expected-") as directory:
        path = session.export(Path(directory) / f"{kind}.pdf", kind)
        return _pdf_text(path)


def test_invalid_pdf_does_not_report_print_success(qtbot, monkeypatch, tmp_path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    invalid_pdf = tmp_path / "invalid.pdf"
    invalid_pdf.write_bytes(b"not a PDF")
    critical = []
    information = []

    monkeypatch.setattr(desktop_main, "QPrinter", MockPrinter)
    monkeypatch.setattr(desktop_main.QMessageBox, "critical", lambda *args: critical.append(args))
    monkeypatch.setattr(desktop_main.QMessageBox, "information", lambda *args: information.append(args))

    result = []
    worker = PrintSendWorker(invalid_pdf, _printer_settings())
    worker.finished.connect(lambda *values: result.append(values))
    worker.run()
    window._on_print_sent(*result[0])

    assert critical and critical[0][1] == "Error de impresión"
    assert information == []
    window.close()


def test_render_failure_aborts_job_and_does_not_report_success(qtbot, monkeypatch, tmp_path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    pdf = tmp_path / "valid.pdf"
    _session().export(pdf, "local")
    critical = []
    information = []
    printer_aborted = []

    class RenderFailurePrinter(MockPrinter):
        def abort(self):
            printer_aborted.append(True)

    class Document:
        Error = QPdfDocument.Error
        Status = QPdfDocument.Status

        def __init__(self, *_args):
            pass

        def load(self, *_args):
            return QPdfDocument.Error.None_

        def status(self):
            return QPdfDocument.Status.Ready

        def pageCount(self):
            return 1

        def render(self, *_args):
            class NullImage:
                def isNull(self):
                    return True

            return NullImage()

        def close(self):
            pass

    class Painter:
        def begin(self, *_args):
            return True

        def end(self):
            return True

    monkeypatch.setattr(desktop_main, "QPrinter", RenderFailurePrinter)
    monkeypatch.setattr(desktop_main, "QPdfDocument", Document)
    monkeypatch.setattr(desktop_main, "QPainter", Painter)
    monkeypatch.setattr(desktop_main.QMessageBox, "critical", lambda *args: critical.append(args))
    monkeypatch.setattr(desktop_main.QMessageBox, "information", lambda *args: information.append(args))
    result = []
    worker = PrintSendWorker(pdf, _printer_settings())
    worker.finished.connect(lambda *values: result.append(values))
    worker.run()
    window._on_print_sent(*result[0])

    assert printer_aborted == [True]
    assert critical and "renderizar" in critical[0][2]
    assert information == []
    window.close()


def test_printer_rejection_does_not_report_success(qtbot, monkeypatch, tmp_path) -> None:
    pdf = tmp_path / "valid.pdf"
    _session().export(pdf, "local")

    class ErrorPrinter(MockPrinter):
        def printerState(self):
            return self.PrinterState.Error

    class Document:
        Error = QPdfDocument.Error
        Status = QPdfDocument.Status

        def load(self, *_args):
            return QPdfDocument.Error.None_

        def status(self):
            return QPdfDocument.Status.Ready

        def pageCount(self):
            return 1

        def render(self, *_args):
            return QImage(8, 8, QImage.Format.Format_RGB32)

        def close(self):
            pass

    class Painter:
        def begin(self, *_args):
            return True

        def drawImage(self, *_args):
            pass

        def end(self):
            return True

    monkeypatch.setattr(desktop_main, "QPrinter", ErrorPrinter)
    monkeypatch.setattr(desktop_main, "QPdfDocument", Document)
    monkeypatch.setattr(desktop_main, "QPainter", Painter)
    results = []
    worker = PrintSendWorker(pdf, _printer_settings())
    worker.finished.connect(lambda *values: results.append(values))

    worker.run()

    assert results[0][0] is False
    assert "no aceptó" in results[0][1]


def test_printer_settings_round_trip_preserves_dialog_options() -> None:
    class SettingsPrinter:
        def __init__(self, values=None):
            page_layout = QPageLayout()
            page_layout.setOrientation(QPageLayout.Orientation.Landscape)
            self.values = values or {
                "printer_name": "Windows PDF printer",
                "page_layout": page_layout,
                "resolution": 600,
                "color_mode": REAL_QPRINTER.ColorMode.GrayScale,
                "duplex": REAL_QPRINTER.DuplexMode.DuplexLongSide,
                "copy_count": 3,
                "collate_copies": True,
                "page_order": REAL_QPRINTER.PageOrder.LastPageFirst,
                "print_range": REAL_QPRINTER.PrintRange.PageRange,
                "from_page": 2,
                "to_page": 4,
                "page_ranges": QPageRanges.fromString("2-4,7"),
                "paper_source": REAL_QPRINTER.PaperSource.Auto,
                "full_page": True,
                "output_format": REAL_QPRINTER.OutputFormat.NativeFormat,
                "output_file_name": "",
                "font_embedding_enabled": False,
            }

        def __getattr__(self, name):
            setter = name.startswith("set")
            attribute = name[3:] if setter else name
            key = re.sub(r"(?<!^)(?=[A-Z])", "_", attribute).lower()
            if setter:
                if attribute == "FromTo":
                    return lambda first, last: self.values.update(
                        from_page=first, to_page=last
                    )
                return lambda *values: self.values.__setitem__(key, values[0] if len(values) == 1 else values)
            if key in self.values:
                return lambda: self.values[key]
            raise AttributeError(name)

    source = SettingsPrinter()
    target = SettingsPrinter({key: None for key in source.values})
    settings = PrinterSettings.from_printer(source)

    settings.apply_to(target)

    for key, value in source.values.items():
        assert target.values[key] == value, key
    assert target.values["page_layout"].orientation() == QPageLayout.Orientation.Landscape


def test_page_range_and_copy_count_are_applied_without_replaying_pages(
    monkeypatch, tmp_path
) -> None:
    rendered_pages = []
    created_printers = []

    class RecordingPrinter(MockPrinter):
        def __init__(self, *_args):
            super().__init__()
            self.copy_count = None
            created_printers.append(self)

        def setCopyCount(self, count):
            self.copy_count = count

    class Document:
        Error = QPdfDocument.Error
        Status = QPdfDocument.Status

        def load(self, *_args):
            return QPdfDocument.Error.None_

        def status(self):
            return QPdfDocument.Status.Ready

        def pageCount(self):
            return 4

        def render(self, page_number, *_args):
            rendered_pages.append(page_number)
            return QImage(8, 8, QImage.Format.Format_RGB32)

        def close(self):
            pass

    class Painter:
        def begin(self, *_args):
            return True

        def drawImage(self, *_args):
            pass

        def end(self):
            return True

    pdf = tmp_path / "invoice with spaces – factura.pdf"
    _session().export(pdf, "local")
    base = _printer_settings()
    settings = PrinterSettings(
        **{
            **base.__dict__,
            "copy_count": 3,
            "print_range": REAL_QPRINTER.PrintRange.PageRange,
            "from_page": 2,
            "to_page": 3,
            "page_ranges": QPageRanges.fromString("2-3"),
        }
    )
    monkeypatch.setattr(desktop_main, "QPrinter", RecordingPrinter)
    monkeypatch.setattr(desktop_main, "QPdfDocument", Document)
    monkeypatch.setattr(desktop_main, "QPainter", Painter)
    result = []
    worker = PrintSendWorker(pdf, settings)
    worker.finished.connect(lambda *values: result.append(values))

    worker.run()

    assert result == [(True, None)]
    assert rendered_pages == [1, 2]
    assert created_printers[0].copy_count == 3


def test_absence_of_printers_shows_error_without_starting_worker(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    warnings = []
    monkeypatch.setattr(desktop_main.QPrinterInfo, "availablePrinters", lambda: [])
    monkeypatch.setattr(desktop_main.QMessageBox, "warning", lambda *args: warnings.append(args))

    window.print_pdf("local")

    assert warnings
    assert warnings[0][1] == "Sin impresoras"
    assert window._print_thread is None
    assert not window._printing
    window.close()


def test_pdf_generation_failure_reports_error_and_removes_temporary_directory(monkeypatch) -> None:
    session = _session()
    created = []
    real_temporary_directory = desktop_main.tempfile.TemporaryDirectory

    def tracked_temporary_directory(*args, **kwargs):
        temporary = real_temporary_directory(*args, **kwargs)
        created.append(temporary)
        return temporary

    monkeypatch.setattr(desktop_main.tempfile, "TemporaryDirectory", tracked_temporary_directory)
    monkeypatch.setattr(session, "export", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("export failed")))
    worker = PrintPdfWorker(session, "local")
    result = []
    worker.finished.connect(lambda *values: result.append(values))

    worker.run()

    assert result[0][0] is None
    assert result[0][1] == "export failed"
    assert result[0][2] is None
    assert result[0][3] is None
    assert created and not Path(created[0].name).exists()


def test_print_buttons_follow_exportable_content_and_processing_state(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert all(button.isEnabled() for button in window.export_buttons)
    assert not any(button.isEnabled() for button in window.print_buttons)

    window.session.products.append(SessionProduct("PACK", "pack", 2, "pack"))
    window.refresh_all()
    assert all(button.isEnabled() for button in window.export_buttons)
    assert not window.print_buttons[0].isEnabled()
    assert window.print_buttons[1].isEnabled()

    window._set_processing(True)
    assert not any(button.isEnabled() for button in window.export_buttons)
    assert not any(button.isEnabled() for button in window.print_buttons)
    window._set_processing(False)
    assert all(button.isEnabled() for button in window.export_buttons)
    assert window.print_buttons[1].isEnabled()
    window.session.reset()
    window.refresh_all()
    assert all(button.isEnabled() for button in window.export_buttons)
    assert not any(button.isEnabled() for button in window.print_buttons)
    window.close()


def test_source_logo_and_small_icon_variants_are_versioned_and_pixel_art() -> None:
    icons = Path(__file__).parents[1] / "app" / "desktop" / "assets" / "icons"
    source = Image.open(icons / "pick_list.png")
    assert source.size == (1254, 1254)
    assert Image.open(icons / "PickList.icns").info["sizes"] == [
        (512, 512, 2), (512, 512, 1), (256, 256, 2), (256, 256, 1),
        (128, 128, 2), (128, 128, 1), (32, 32, 2), (16, 16, 2),
    ]
    assert Image.open(icons / "PickList.ico").info["sizes"] == {
        (16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)
    }
