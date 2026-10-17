from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.entities import ProductCandidate, SourceFile, SourceDocumentMetadata
from app.services.extractor import extract_pdf, parse_pdf


@pytest.mark.parametrize("fixture_name", [
    "DTE-PDF-76353833-8-33-111801.pdf",
    "DTE-PDF-76353833-8-33-111808.pdf",
    "DTE-PDF-76353833-8-33-111830.pdf",
])
def test_database_free_extraction_matches_legacy_adapter(fixture_name: str) -> None:
    """Characterize the local path against the currently used DB adapter."""
    fixture = Path(__file__).parent / "fixtures" / fixture_name
    pure_result = extract_pdf(fixture)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        source = SourceFile(filename=fixture.name, stored_path=str(fixture))
        db.add(source)
        db.commit()
        db.refresh(source)
        legacy_products = parse_pdf(db, source)
        persisted = db.query(ProductCandidate).filter_by(source_file_id=source.id).all()
        metadata = db.get(SourceDocumentMetadata, source.id)

    def identity(product):
        return (product.page_number, product.sku, product.descripcion_exacta,
                product.cantidad, product.tipo_presentacion, product.unit, product.observations)

    assert [identity(product) for product in pure_result.products] == [identity(product) for product in legacy_products]
    assert [(row.page_number, row.sku, row.description_exact, row.quantity, row.presentation,
             row.unit, row.observations) for row in persisted] == [
        (p.page_number, p.sku, p.descripcion_exacta, p.cantidad, p.tipo_presentacion.lower(), p.unit, p.observations)
        for p in pure_result.products
    ]
    assert metadata.document_number == pure_result.summary.number
    assert metadata.payment_condition == pure_result.summary.payment_condition
