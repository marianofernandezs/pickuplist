from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import Base
from app.desktop.application import PickListSession, ProcessedBatch, SessionProduct, process_files
from app.desktop.main import MainWindow
from app.models.entities import BatchTask, ProcessingBatch, ProductCandidate, SourceDocumentMetadata, SourceFile
from app.services.document_summary import DocumentSummary
from app.services.extractor import ParsedProduct, PdfExtraction, extract_pdf, parse_pdf
from app.services.quantity_validation import InvalidProductQuantity


def _registry_pdf(path: Path, products: list[str]) -> None:
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "REGISTRO INTERNO")
        page.insert_text((40, 60), "DISMINUYE STOCK")
        for index, product in enumerate(products, start=1):
            page.insert_text((40, 100 + index * 18), product)
        pdf.save(path)


def test_extraction_rejects_complete_registry_pdf_with_product_and_original_quantity(tmp_path) -> None:
    path = tmp_path / "registro-decimal.pdf"
    _registry_pdf(path, [
        "BODEGATEST1 PRODUCTO VALIDO 2 CAJA",
        "BODEGATEST2 JABON 1,5 LTS 1,5 PACK",
    ])

    with pytest.raises(InvalidProductQuantity) as error:
        extract_pdf(path)

    message = str(error.value)
    assert "registro-decimal.pdf" in message
    assert "JABON 1,5 LTS" in message
    assert "(1,5)" in message
    assert "Solo se permiten cantidades enteras" in message


def test_generic_pdf_quantity_cell_that_was_truncated_is_rejected(tmp_path, monkeypatch) -> None:
    import app.services.extractor as extractor

    path = tmp_path / "generic.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "FACTURA ELECTRONICA")
        pdf.save(path)

    class TablePage:
        def extract_tables(self):
            return [[
                ["Glosa", "Cantidad"],
                ["PRODUCTO VALIDO", "2 CAJA"],
                ["JABON 1,5 LTS", "1,5 PACK"],
            ]]

    class PdfTables:
        pages = [TablePage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(extractor.pdfplumber, "open", lambda _path: PdfTables())
    with pytest.raises(InvalidProductQuantity) as error:
        extract_pdf(path)
    assert "generic.pdf" in str(error.value)
    assert "JABON 1,5 LTS" in str(error.value)
    assert "(1,5)" in str(error.value)


def test_web_persistence_does_not_save_partial_document_when_quantity_is_invalid(tmp_path) -> None:
    path = tmp_path / "invalid.pdf"
    _registry_pdf(path, [
        "BODEGATEST1 PRODUCTO VALIDO 2 CAJA",
        "BODEGATEST2 PRODUCTO INVALIDO 2.5 PACK",
    ])
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            source = SourceFile(filename=path.name, stored_path=str(path), status="processing")
            db.add(source)
            db.commit()

            with pytest.raises(InvalidProductQuantity, match="invalid.pdf"):
                parse_pdf(db, source)

            assert db.query(ProductCandidate).filter_by(source_file_id=source.id).count() == 0
            assert db.query(SourceDocumentMetadata).filter_by(source_file_id=source.id).count() == 0
    finally:
        engine.dispose()


def test_web_worker_marks_invalid_document_failed_and_records_error(monkeypatch) -> None:
    from app.workers import tasks

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(
        tasks,
        "parse_pdf",
        lambda *_args: (_ for _ in ()).throw(
            InvalidProductQuantity("PRODUCTO WEB", "1,5", document="web.pdf")
        ),
    )
    batch_id = "b0000000-0000-0000-0000-000000000001"
    task_id = "quantity-rejected-task"
    with session_factory() as db:
        batch = ProcessingBatch(id=batch_id, total_files=1, created_by_email="test@example.invalid")
        source = SourceFile(filename="web.pdf", stored_path="unused.pdf", status="queued")
        db.add_all([batch, source])
        db.flush()
        source_id = source.id
        db.add(BatchTask(batch_id=batch_id, source_file_id=source_id, task_id=task_id, status="queued"))
        db.commit()

    task = tasks.process_source_file
    task.push_request(id=task_id, retries=0)
    try:
        assert task.run(batch_id, source_id) == {"status": "failed"}
    finally:
        task.pop_request()

    with session_factory() as db:
        source = db.get(SourceFile, source_id)
        batch = db.get(ProcessingBatch, batch_id)
        task_row = db.query(BatchTask).filter_by(task_id=task_id).one()
        assert source is not None and source.status == "failed"
        assert batch is not None and batch.status == "failed" and batch.failed_files == 1
        assert task_row.status == "failed"
        assert "PRODUCTO WEB" in (task_row.error_message or "")
        assert "web.pdf" in (task_row.error_message or "")
        assert db.query(ProductCandidate).filter_by(source_file_id=source_id).count() == 0
    engine.dispose()


def test_desktop_mixed_batch_keeps_only_valid_documents_and_previous_session(tmp_path, monkeypatch) -> None:
    previous = ProcessedBatch(
        (),
        (SessionProduct("PRODUCTO PREVIO", "caja", 5, "caja"),),
        (DocumentSummary("PREVIO", "Contado"),),
    )
    session = PickListSession.empty()
    session.add_batch(previous)
    good = tmp_path / "bueno.pdf"
    bad = tmp_path / "malo.pdf"
    good.touch()
    bad.touch()
    good_extraction = PdfExtraction(
        products=[
            # The description's decimal is a package size, not its quantity.
            ParsedProduct("SKU1", "JABON 1,5 LTS", 2, "CAJA", 1, "caja"),
        ],
        summary=DocumentSummary("BUENO", "Contado"),
        page_count=1,
        requires_ocr=False,
        lines_by_page=[["línea"]],
    )
    calls = []

    def extract(path):
        calls.append(Path(path).name)
        if Path(path).name == bad.name:
            raise InvalidProductQuantity("PRODUCTO INVALIDO", "0,25", document=bad.name)
        return good_extraction

    monkeypatch.setattr("app.desktop.application.extract_pdf", extract)
    batch = process_files([good, bad])

    assert batch is not None
    assert calls == [good.name, bad.name]
    assert [source.status for source in batch.sources] == ["processed", "failed"]
    assert "malo.pdf" in (batch.sources[1].error or "")
    assert "PRODUCTO INVALIDO" in (batch.sources[1].error or "")
    assert [product.description_exact for product in batch.products] == ["JABON 1,5 LTS"]
    assert [summary.number for summary in batch.summaries] == ["BUENO"]

    session.add_batch(batch)
    assert [product.description_exact for product in session.products] == ["PRODUCTO PREVIO", "JABON 1,5 LTS"]
    assert [summary.number for summary in session.summaries] == ["PREVIO", "BUENO"]


def test_desktop_shows_document_quantity_error_and_exports_only_successful_documents(
    qtbot, monkeypatch, tmp_path
) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    import app.desktop.application as application

    window = MainWindow()
    qtbot.addWidget(window)
    paths = [str(tmp_path / "bueno.pdf"), str(tmp_path / "malo.pdf")]
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: (paths, ""))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, title, message: warnings.append((title, message)))

    def extract(path):
        if Path(path).name == "malo.pdf":
            raise InvalidProductQuantity("PRODUCTO CON ERROR", "1,5", document=Path(path).name)
        return PdfExtraction(
            [ParsedProduct("SKU", "PRODUCTO BUENO", 3, "CAJA", 1, "caja")],
            DocumentSummary("FACTURA BUENA", "Contado"), 1, False, [["texto"]],
        )

    monkeypatch.setattr(application, "extract_pdf", extract)
    window.choose_files()
    qtbot.waitUntil(lambda: window._worker_thread is None, timeout=5000)

    assert len(warnings) == 1
    assert "malo.pdf" in warnings[0][1]
    assert "PRODUCTO CON ERROR" in warnings[0][1]
    assert "1,5" in warnings[0][1]
    assert [source.status for source in window.session.sources] == ["processed", "failed"]
    assert [product.description_exact for product in window.session.products] == ["PRODUCTO BUENO"]
    assert [summary.number for summary in window.session.summaries] == ["FACTURA BUENA"]

    bodega = window.session.export(tmp_path / "bodega.pdf", "bodega")
    local = window.session.export(tmp_path / "local.pdf", "local")
    with fitz.open(bodega) as document:
        bodega_text = " ".join(page.get_text() for page in document)
    with fitz.open(local) as document:
        local_text = " ".join(page.get_text() for page in document)
    assert "PRODUCTO BUENO" in bodega_text
    assert "PRODUCTO CON ERROR" not in bodega_text
    assert "FACTURA BUENA" in bodega_text
    assert "FACTURA RECHAZADA" not in bodega_text
    assert "PRODUCTO CON ERROR" not in local_text
    assert "FACTURA RECHAZADA" not in local_text
    assert window.add_button.isEnabled()
    assert all(button.isEnabled() for button in window.export_buttons)
    assert window.print_buttons[0].isEnabled()
    assert not window.print_buttons[1].isEnabled()
    window.close()
