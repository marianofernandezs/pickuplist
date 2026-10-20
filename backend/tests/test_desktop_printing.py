from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QPrintDialog

from app.desktop.application import LocalSource, PickListSession, SessionProduct
from app.desktop import main as desktop_main
from app.desktop.main import MainWindow, PrintPdfWorker, PrintSendWorker
from app.services.document_summary import DocumentSummary


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
    worker.finished.connect(lambda path, error, temporary: result.append((path, error, temporary)))
    worker.run()
    path, error, temporary = result[0]
    assert error is None
    assert path and Path(path).is_file()
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


def test_cancelled_print_dialog_does_not_send_or_report_success(qtbot, monkeypatch, tmp_path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    pdf = tmp_path / "print.pdf"
    _session().export(pdf, "local")
    messages = []

    class Printer:
        PrinterMode = desktop_main.QPrinter.PrinterMode

        def __init__(self, *_args):
            pass

    class Dialog:
        DialogCode = QPrintDialog.DialogCode

        def __init__(self, *_args):
            pass

        def exec(self):
            return QPrintDialog.DialogCode.Rejected

    monkeypatch.setattr(desktop_main, "QPrinter", Printer)
    monkeypatch.setattr(desktop_main, "QPrintDialog", Dialog)
    monkeypatch.setattr(desktop_main.QMessageBox, "information", lambda *args: messages.append(args))
    window._show_print_dialog_and_send(pdf)

    assert messages == []
    window.close()


def test_invalid_pdf_does_not_report_print_success(qtbot, monkeypatch, tmp_path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    invalid_pdf = tmp_path / "invalid.pdf"
    invalid_pdf.write_bytes(b"not a PDF")
    critical = []
    information = []

    class Printer:
        PrinterMode = desktop_main.QPrinter.PrinterMode
        Unit = desktop_main.QPrinter.Unit
        PrinterState = desktop_main.QPrinter.PrinterState

        def __init__(self, *_args):
            pass

        def isValid(self):
            return True

    class Dialog:
        DialogCode = QPrintDialog.DialogCode

        def __init__(self, *_args):
            pass

        def exec(self):
            return QPrintDialog.DialogCode.Accepted

    monkeypatch.setattr(desktop_main, "QPrinter", Printer)
    monkeypatch.setattr(desktop_main, "QPrintDialog", Dialog)
    monkeypatch.setattr(desktop_main.QMessageBox, "critical", lambda *args: critical.append(args))
    monkeypatch.setattr(desktop_main.QMessageBox, "information", lambda *args: information.append(args))

    result = []
    worker = PrintSendWorker(invalid_pdf, object())
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

    class Printer:
        PrinterMode = desktop_main.QPrinter.PrinterMode
        Unit = desktop_main.QPrinter.Unit
        PrinterState = desktop_main.QPrinter.PrinterState

        def __init__(self, *_args):
            pass

        def isValid(self):
            return True

        def pageRect(self, *_args):
            return QRectF(0, 0, 500, 700)

        def newPage(self):
            return True

        def printerState(self):
            return self.PrinterState.Idle

        def abort(self):
            printer_aborted.append(True)

    class Dialog:
        DialogCode = QPrintDialog.DialogCode

        def __init__(self, *_args):
            pass

        def exec(self):
            return QPrintDialog.DialogCode.Accepted

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

    monkeypatch.setattr(desktop_main, "QPrinter", Printer)
    monkeypatch.setattr(desktop_main, "QPrintDialog", Dialog)
    monkeypatch.setattr(desktop_main, "QPdfDocument", Document)
    monkeypatch.setattr(desktop_main, "QPainter", Painter)
    monkeypatch.setattr(desktop_main.QMessageBox, "critical", lambda *args: critical.append(args))
    monkeypatch.setattr(desktop_main.QMessageBox, "information", lambda *args: information.append(args))
    result = []
    worker = PrintSendWorker(pdf, Printer())
    worker.finished.connect(lambda *values: result.append(values))
    worker.run()
    window._on_print_sent(*result[0])

    assert printer_aborted == [True]
    assert critical and "renderizar" in critical[0][2]
    assert information == []
    window.close()


def test_printer_rejection_does_not_report_success(monkeypatch, tmp_path) -> None:
    pdf = tmp_path / "valid.pdf"
    _session().export(pdf, "local")

    class Printer:
        Unit = desktop_main.QPrinter.Unit
        PrinterState = desktop_main.QPrinter.PrinterState

        def pageRect(self, *_args):
            return QRectF(0, 0, 500, 700)

        def printerState(self):
            return self.PrinterState.Error

        def abort(self):
            pass

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

    monkeypatch.setattr(desktop_main, "QPdfDocument", Document)
    monkeypatch.setattr(desktop_main, "QPainter", Painter)
    results = []
    worker = PrintSendWorker(pdf, Printer())
    worker.finished.connect(lambda *values: results.append(values))

    worker.run()

    assert results[0][0] is False
    assert "no aceptó" in results[0][1]


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
