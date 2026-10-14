from pathlib import Path

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.entities import SourceDocumentMetadata, SourceFile
from app.services.document_summary import extract_payment_condition
from app.services.extractor import parse_pdf
from app.services.pdf_exporter import export_vige_pdf

REAL_INVOICES = [
    ("DTE-PDF-76353833-8-33-111808.pdf", "Contado"),
    ("DTE-PDF-76353833-8-33-111801.pdf", "CREDITO 30 DIAS"),
    ("DTE-PDF-76353833-8-33-111830.pdf", "Contado"),
]


@pytest.mark.parametrize("filename, expected", REAL_INVOICES)
def test_extract_payment_condition_real_invoice(filename, expected):
    path = Path(__file__).parent / "fixtures" / filename
    with fitz.open(path) as pdf:
        assert extract_payment_condition(pdf) == expected


@pytest.mark.parametrize("filename, expected", REAL_INVOICES)
def test_reader_persists_real_invoice_payment_condition(filename, expected):
    path = Path(__file__).parent / "fixtures" / filename
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            source = SourceFile(filename=filename, stored_path=str(path))
            db.add(source)
            db.commit()
            products = parse_pdf(db, source)
            metadata = db.get(SourceDocumentMetadata, source.id)
            assert metadata is not None
            assert metadata.payment_condition == expected
            assert source.status == "processed"
            assert products
    finally:
        engine.dispose()


@pytest.mark.parametrize("other_field", ["Observaciones: Entregar por la tarde", "Forma de pago: Transferencia"])
def test_absent_payment_conditions_return_none(other_field):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "FACTURA ELECTRONICA\nN º 100")
        page.insert_text((40, 100), other_field)
        assert extract_payment_condition(pdf) is None


@pytest.mark.parametrize("value", ["Crédito - 30 días; transferencia bancaria.", "Pago total anticipado", "30"])
def test_value_preserves_case_accents_and_punctuation(value):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 100), "Condiciones de pago:")
        page.insert_text((250, 100), value)
        assert extract_payment_condition(pdf) == value


def test_value_collapses_only_unnecessary_spaces():
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 100), "Condiciones de pago:  Crédito   30   días.")
        assert extract_payment_condition(pdf) == "Crédito 30 días."


def test_reader_persists_none_and_export_keeps_missing_value_label(tmp_path):
    path = tmp_path / "no-payment-field.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "FACTURA ELECTRONICA\nN º 100\nObservaciones: Entregar por la tarde")
        pdf.save(path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            source = SourceFile(filename=path.name, stored_path=str(path))
            db.add(source)
            db.commit()
            parse_pdf(db, source)
            metadata = db.get(SourceDocumentMetadata, source.id)
            assert metadata is not None
            assert metadata.payment_condition is None
            output = export_vige_pdf(db, tmp_path / "export.pdf", include_document_summary=True)
            with fitz.open(output) as result:
                assert "No informada" in result[-1].get_text()
                assert "Total facturas: 1" in result[-1].get_text()
    finally:
        engine.dispose()
