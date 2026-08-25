from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.entities import ProductCandidate, SourceFile
from app.services.extractor import parse_pdf


def _registro_interno_fixture() -> Path:
    configured = os.getenv("REGISTRO_INTERNO_PDF")
    candidates = [
        Path(configured) if configured else None,
        Path("/Users/mariano/Downloads/Facturas Piqueo 2/Registro_interno_disminuye_stock_1546.pdf"),
        Path(__file__).parent / "fixtures/Registro_interno_disminuye_stock_1546.pdf",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    pytest.skip("PDF de integración no disponible; define REGISTRO_INTERNO_PDF para ejecutarlo.")


def test_parse_pdf_registro_interno_fallback_persists_critical_product() -> None:
    fixture = _registro_interno_fixture()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        source_file = SourceFile(filename=fixture.name, stored_path=str(fixture))
        db.add(source_file)
        db.commit()
        db.refresh(source_file)

        products = parse_pdf(db, source_file)
        candidates = db.query(ProductCandidate).all()

    assert any(
        p.sku == "BODEGAAS54"
        and p.descripcion_exacta == "ALCOHOL SPRAY ECOSAFE 5 LTS X 4 BIDONES"
        and p.cantidad == 1
        and p.tipo_presentacion == "CAJA"
        and p.page_number == 2
        for p in products
    )
    assert any(
        p.sku == "BODEGAAS54"
        and p.description_exact == "ALCOHOL SPRAY ECOSAFE 5 LTS X 4 BIDONES"
        and p.quantity == 1
        and p.presentation == "caja"
        and p.page_number == 2
        for p in candidates
    )
    assert not any("BENEXIA CAMBIAR" in p.descripcion_exacta for p in products)

    page_one_keys = [
        (
            p.sku,
            p.descripcion_exacta.upper().strip(),
            p.cantidad,
            p.tipo_presentacion,
        )
        for p in products
        if p.page_number == 1
    ]
    assert len(page_one_keys) == len(set(page_one_keys))
