from datetime import UTC, datetime
from pathlib import Path

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.entities import (
    ExtractedLine,
    ProductCandidate,
    SourceDocumentMetadata,
    SourceFile,
)
from app.services.document_summary import (
    collect_document_summaries,
    extract_document_summary,
    parse_document_summary,
)
from app.services.pdf_exporter import export_vige_pdf


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_document(db, number, payment="Contado", *, status="processed", created_at=None):
    source = SourceFile(filename=f"{number}.pdf", stored_path="unused.pdf", status=status,
                        created_at=created_at or datetime(2026, 1, 1, tzinfo=UTC))
    db.add(source)
    db.flush()
    # Insert in reverse order to verify that collection uses document position.
    lines = ["FACTURA ELECTRÓNICA", f"N º {number}", "S.I.I. - ARICA", "Condiciones de pago", payment, "Monto Neto"]
    for index, line in reversed(list(enumerate(lines))):
        db.add(ExtractedLine(source_file_id=source.id, page_number=1, block_index=index, raw_text=line))
    db.flush()
    return source


@pytest.mark.parametrize("label", ["N º 106978", "N°106978", "Nº: 106978", "No. 106978", "N o 106978"])
def test_invoice_number_formats(label):
    summary = parse_document_summary(["FACTURA ELECTRÓNICA", label, "S.I.I. - ARICA",
                                      "Condiciones de pago", "CREDITO 30 DIAS", "Vencimiento", "27-06-2026"])
    assert summary.number == "106978"
    assert summary.payment_condition == "CREDITO 30 DIAS"


def test_registry_has_fixed_label():
    summary = parse_document_summary(["REGISTRO INTERNO", "DISMINUYE STOCK", "N º 1464", "Señor(es)"])
    assert summary.number == "1464"
    assert summary.payment_condition == "registro interno stock"


def test_missing_fields_and_unrelated_numbers():
    summary = parse_document_summary(["FACTURA ELECTRÓNICA", "S.I.I. - ARICA",
                                      "BANDEJA N° 5", "Resolución Ex. SII N° 80 de 2014"])
    assert summary.number == "No identificado"
    assert summary.payment_condition is None
    assert parse_document_summary([]) == summary


def test_multiline_and_inline_payment():
    for label in ["Condiciones de pago: CREDITO", "Condiciones de pago\nCREDITO"]:
        summary = parse_document_summary(["FACTURA ELECTRÓNICA", "N º 123", "S.I.I. - ARICA",
                                          *label.splitlines(), "30 DIAS", "OBSERVACIONES", "Entregar mañana"])
        assert summary.payment_condition == "CREDITO 30 DIAS"


@pytest.mark.parametrize("lines, expected", [
    (["Condiciones de", "pago", "Contado", "OBSERVACIONES"], "Contado"),
    (["Condición de pago: Crédito", "30 días", "Vencimiento: 01-01-2027"], "Crédito 30 días"),
    (["Cliente: Empresa Condiciones Pago: CONTADO Fecha: 01-01-2027"], "CONTADO"),
    (["CONDICIONES DE VENTA", "Crédito 60 días", "Monto Neto"], "Crédito 60 días"),
    (["Forma de Pago: Transferencia bancaria", "Monto Neto"], "Transferencia bancaria"),
    (["Forma de pago: Transferencia", "Condiciones de pago: Crédito 30 días"], "Crédito 30 días"),
    (["Condiciones de pago:", "Vencimiento: 01-01-2027", "Cliente: Empresa"], None),
])
def test_payment_label_variants(lines, expected):
    assert parse_document_summary(lines).payment_condition == expected


@pytest.mark.parametrize("layout", ["right", "below", "wrapped", "reversed", "continuation"])
def test_pdf_geometry_finds_payment_without_relying_on_text_order(layout):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "FACTURA ELECTRONICA")
        page.insert_text((40, 60), "N º 123")
        if layout == "reversed":
            page.insert_text((250, 100), "CREDITO 30 DIAS")
            page.insert_text((40, 100), "Condiciones de pago:")
        elif layout == "wrapped":
            page.insert_text((40, 100), "Condiciones de")
            page.insert_text((40, 114), "pago")
            page.insert_text((250, 107), "CREDITO 30 DIAS")
        elif layout == "below":
            page.insert_text((40, 100), "Condiciones de pago")
            page.insert_text((300, 100), "Fecha")
            page.insert_text((300, 120), "01-01-2027")
            page.insert_text((40, 120), "CREDITO 30 DIAS")
        elif layout == "continuation":
            page.insert_text((40, 100), "Condiciones de pago")
            page.insert_text((250, 100), "CREDITO")
            page.insert_text((250, 114), "30 DIAS")
        else:
            page.insert_text((40, 100), "Condiciones de pago")
            page.insert_text((250, 100), "CREDITO 30 DIAS")
        page.insert_text((40, 145), "Observaciones")
        page.insert_text((40, 165), "ENTREGAR POR LA TARDE")
        summary = extract_document_summary(pdf)
        assert summary.number == "123"
        assert summary.payment_condition == "CREDITO 30 DIAS"


def test_processing_persists_metadata_and_export_uses_it(db, tmp_path):
    from app.services.extractor import parse_pdf

    path = tmp_path / "invoice.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "FACTURA ELECTRONICA\nN º 321")
        page.insert_text((40, 100), "Condiciones de\npago")
        page.insert_text((250, 107), "CREDITO 60 DIAS")
        pdf.save(path)
    source = SourceFile(filename=path.name, stored_path=str(path))
    db.add(source)
    db.commit()
    parse_pdf(db, source)
    parse_pdf(db, source)
    metadata, = db.query(SourceDocumentMetadata).all()
    assert metadata.document_number == "321"
    assert metadata.payment_condition == "CREDITO 60 DIAS"
    path.unlink()
    summary, = collect_document_summaries(db)
    assert summary.payment_condition == "CREDITO 60 DIAS"


def test_pdf_missing_payment_does_not_use_observations():
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 100), "Condiciones de pago")
        page.insert_text((40, 120), "Observaciones")
        page.insert_text((40, 140), "ENTREGAR POR LA TARDE")
        assert extract_document_summary(pdf).payment_condition is None


def test_legacy_upload_reads_pdf_and_reset_deletes_metadata(db, tmp_path, monkeypatch):
    from app.api import routes

    path = tmp_path / "legacy.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "FACTURA ELECTRONICA\nN º 444")
        page.insert_text((40, 100), "Condiciones de\npago")
        page.insert_text((250, 107), "Contado")
        pdf.save(path)
    source = SourceFile(filename=path.name, stored_path=str(path), status="processed")
    db.add(source)
    db.commit()
    summary, = collect_document_summaries(db)
    assert summary.number == "444"
    assert summary.payment_condition == "Contado"
    db.add(SourceDocumentMetadata(source_file_id=source.id, document_number="444", payment_condition="Contado"))
    db.commit()
    monkeypatch.setattr(routes.settings, "output_dir", str(tmp_path))
    routes.reset_iteration(db=db, current_user=None)
    assert db.query(SourceDocumentMetadata).count() == 0
    assert db.query(SourceFile).count() == 0


def test_processed_documents_ordered_by_upload_once_per_file(db):
    later = add_document(db, "222", created_at=datetime(2026, 1, 2, tzinfo=UTC))
    add_document(db, "111", created_at=datetime(2026, 1, 1, tzinfo=UTC))
    for status in ["uploaded", "processing", "failed", "requires_ocr"]:
        add_document(db, "999", status=status)
    db.add(ExtractedLine(source_file_id=later.id, page_number=2, block_index=0,
                         raw_text="FACTURA ELECTRÓNICA\nN º 222\nS.I.I. - ARICA"))
    db.flush()
    summaries = collect_document_summaries(db)
    assert [row.number for row in summaries] == ["111", "222"]
    assert [row.payment_condition for row in summaries] == ["Contado", "Contado"]


def test_existing_processed_document_without_text(db):
    db.add(SourceFile(filename="empty.pdf", stored_path="unused.pdf", status="processed"))
    db.flush()
    summary, = collect_document_summaries(db)
    assert summary.number == "No identificado"
    assert summary.payment_condition is None


def test_summary_only_when_enabled_and_independent_of_products(db, tmp_path):
    source = add_document(db, "123")
    db.add(ProductCandidate(source_file_id=source.id, page_number=1, description_exact="Producto local",
                            quantity=2, presentation="pack"))
    db.flush()
    for enabled in [False, True]:
        path = export_vige_pdf(db, tmp_path / f"summary-{enabled}.pdf", allowed_presentations=("caja",),
                               include_document_summary=enabled)
        with fitz.open(path) as pdf:
            assert len(pdf) == (2 if enabled else 1)
            assert "Producto local" not in pdf[0].get_text()
            if enabled:
                assert "Codigo de facturas escaneadas" in pdf[-1].get_text()
                assert "123" in pdf[-1].get_text()
                assert "Contado" in pdf[-1].get_text()
                assert "Total facturas: 1" in pdf[-1].get_text()
            else:
                assert "Total facturas" not in pdf[0].get_text()


def test_empty_summary_still_adds_page(db, tmp_path):
    path = export_vige_pdf(db, tmp_path / "empty.pdf", include_document_summary=True)
    with fitz.open(path) as pdf:
        assert len(pdf) == 2
        assert "Sin documentos procesados" in pdf[-1].get_text()
        assert "Total facturas: 0" in pdf[-1].get_text()


def test_summary_paginates_and_wraps_without_losing_text(db, tmp_path):
    for number in range(1000, 1070):
        add_document(db, str(number), "CREDITO 30 DIAS " * 10 + "FIN CONDICION")
    path = export_vige_pdf(db, tmp_path / "many.pdf", include_document_summary=True)
    with fitz.open(path) as pdf:
        assert len(pdf) > 2
        text = "\n".join(page.get_text() for page in pdf)
        assert text.count("FIN CONDICION") == 70
        assert text.count("Total facturas:") == 1
        assert "Total facturas: 70" in pdf[-1].get_text()
        for number in range(1000, 1070):
            assert text.count(str(number)) == 1
        for page in list(pdf)[1:]:
            assert "Codigo de facturas escaneadas" in page.get_text()
            assert "Número de documento" in page.get_text()
            for x0, y0, x1, y1, *_ in page.get_text("blocks"):
                assert 39 <= x0 < x1 <= page.rect.width - 39
                assert 25 <= y0 < y1 <= page.rect.height - 39


def test_only_bodega_route_enables_summary(db, tmp_path, monkeypatch):
    from app.api import routes

    calls = []
    monkeypatch.setattr(routes.settings, "output_dir", str(tmp_path))
    monkeypatch.setattr(routes, "export_vige_pdf", lambda *args, **kwargs: calls.append(kwargs))
    routes.export_pickeo_bodega_pdf(db=db, current_user=None)
    routes.export_pickeo_local_pdf(db=db, current_user=None)
    routes.export_pdf(db=db, current_user=None)
    assert calls[0]["include_document_summary"] is True
    assert all(not call.get("include_document_summary", False) for call in calls[1:])


@pytest.mark.parametrize("document_count", [28, 29, 30])
def test_total_counts_only_included_files_and_fits_on_final_page(db, tmp_path, document_count):
    for number in range(1000, 1000 + document_count - 1):
        add_document(db, str(number))
    registry = add_document(db, "1464")
    db.query(ExtractedLine).filter(ExtractedLine.source_file_id == registry.id).delete()
    db.add(ExtractedLine(source_file_id=registry.id, page_number=1, block_index=0,
                         raw_text="REGISTRO INTERNO\nDISMINUYE STOCK\nN º 1464\nSeñor(es)"))
    for status in ["uploaded", "processing", "failed"]:
        add_document(db, "999", status=status)
    db.flush()
    path = export_vige_pdf(db, tmp_path / "total.pdf", include_document_summary=True)
    with fitz.open(path) as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        assert text.count("Total facturas:") == 1
        assert f"Total facturas: {document_count}" in pdf[-1].get_text()
        assert "registro interno stock" in pdf[-1].get_text()
        assert "999" not in text
        total_block, = [block for block in pdf[-1].get_text("blocks") if "Total facturas:" in block[4]]
        assert total_block[3] <= pdf[-1].rect.height - 39


def test_single_condition_longer_than_page_and_unbroken_word(db, tmp_path):
    payment = "PLAZO " * 1000 + "X" * 200 + " FIN CONDICION"
    add_document(db, "123", payment)
    path = export_vige_pdf(db, tmp_path / "oversized.pdf", include_document_summary=True)
    with fitz.open(path) as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        assert len(pdf) > 2
        assert text.count("PLAZO") == 1000
        assert text.count("X") == 200
        assert "FIN CONDICION" in text
        assert "Total facturas: 1" in pdf[-1].get_text()
        for page in list(pdf)[1:]:
            for x0, y0, x1, y1, *_ in page.get_text("blocks"):
                assert 39 <= x0 < x1 <= page.rect.width - 39
                assert 25 <= y0 < y1 <= page.rect.height - 39


EXAMPLES = Path(__file__).resolve().parents[2] / "Facturas Piqueo"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.pdf")), ids=lambda path: path.name)
def test_supplied_examples(path):
    with fitz.open(path) as pdf:
        summary = parse_document_summary([line for page in pdf for line in page.get_text().splitlines()])
    expected_number = path.stem.rsplit("-", 1)[-1] if path.name.startswith("DTE") else "1464"
    credit_30 = {"106978", "106988", "106990", "106994", "107001", "107003"}
    expected_payment = ("registro interno stock" if expected_number == "1464" else
                        "CREDITO 30 DIAS" if expected_number in credit_30 else
                        "CREDITO 7 DIAS" if expected_number == "106992" else "Contado")
    assert summary.number == expected_number
    assert summary.payment_condition == expected_payment
