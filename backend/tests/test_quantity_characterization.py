from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.desktop.application import PickListSession, SessionProduct
from app.models.entities import ProductCandidate, SourceDocumentMetadata, SourceFile
from app.schemas.vige import ProductOut
from app.services.classifier import parse_quantity_cell
from app.services.consolidator import consolidate_products
from app.services.document_summary import DocumentSummary
from app.services.pdf_exporter import export_vige_pdf
from app.services.registro_interno_parser import parseRegistroInternoBuffer
from app.services.quantity_validation import InvalidProductQuantity


@pytest.mark.parametrize("quantity_text", ["2 CAJA", "15 PACK", "100 UN"])
def test_registro_interno_accepts_integer_quantities(quantity_text: str) -> None:
    parsed = parseRegistroInternoBuffer(f"BODEGATEST1 PRODUCTO SINTETICO {quantity_text}")

    assert parsed is not None
    assert isinstance(parsed["cantidad"], int)


@pytest.mark.parametrize("quantity", ["1,5", "2.5", "0,25"])
def test_registry_parser_rejects_decimal_quantities(quantity: str) -> None:
    with pytest.raises(InvalidProductQuantity, match="PRODUCTO SINTETICO"):
        parseRegistroInternoBuffer(f"BODEGATEST1 PRODUCTO SINTETICO {quantity} CAJA")


def test_ambiguous_registry_separator_is_rejected_without_thousands_guess() -> None:
    with pytest.raises(InvalidProductQuantity, match="ambigua"):
        parseRegistroInternoBuffer("BODEGATEST1 PRODUCTO SINTETICO 1.000 CAJA")


def test_decimal_in_registry_description_is_valid_when_quantity_is_integer() -> None:
    parsed = parseRegistroInternoBuffer("BODEGATEST1 JABON 1,5 LTS 2 CAJA")
    assert parsed is not None
    assert parsed["descripcion_exacta"] == "JABON 1,5 LTS"
    assert parsed["cantidad"] == 2
    assert type(parsed["cantidad"]) is int


@pytest.mark.parametrize(
    ("cell", "presentation", "quantity"),
    [
        ("12 CAJA", "caja", 12),
        ("3 PACK", "pack", 3),
        ("4 UN", "unitario", 4),
        ("CAJA", "caja", None),
        ("SIN DATO", "ambiguo", None),
    ],
)
def test_invoice_quantity_cells_currently_use_integer_parser(
    cell: str, presentation: str, quantity: int | None,
) -> None:
    parsed = parse_quantity_cell(cell)

    assert (parsed.presentation, parsed.quantity) == (presentation, quantity)


@pytest.mark.parametrize("cell", ["1,5 CAJA", "2.5 PACK", "0,25 UN"])
def test_invoice_quantity_cell_rejects_fractional_values(cell: str) -> None:
    with pytest.raises(InvalidProductQuantity, match="decimal inválida"):
        parse_quantity_cell(cell, description="PRODUCTO SINTETICO")


def test_decimal_in_product_description_is_not_treated_as_quantity() -> None:
    parsed = parse_quantity_cell("2 CAJA", description="JABON 1,5 LTS")
    assert parsed.quantity == 2


def _synthetic_rows() -> list[dict[str, object]]:
    return [
        {"description_exact": " ZAPATO   NEGRO ", "presentation": "caja", "quantity": 1, "unit": "caja"},
        # The current grouping key is description + presentation, not unit.
        {"description_exact": "zapato negro", "presentation": "caja", "quantity": 2, "unit": "unidad"},
        {"description_exact": "Zapato Negro", "presentation": "pack", "quantity": 2, "unit": "pack"},
        {"description_exact": "LAPIZ", "presentation": "unitario", "quantity": 5, "unit": "un"},
    ]


def _pdf_text(path: Path) -> str:
    with fitz.open(path) as document:
        return " ".join(page.get_text() for page in document)


def test_web_and_desktop_paths_match_explicit_synthetic_consolidation_and_exports(tmp_path) -> None:
    """Compare persisted web and in-memory desktop paths against fixed synthetic data."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    desktop = PickListSession.empty()
    desktop.summaries.append(DocumentSummary("SYN-100", "Contado"))

    with Session(engine) as db:
        source = SourceFile(filename="synthetic.pdf", stored_path="not-a-real-file.pdf", status="processed")
        db.add(source)
        db.flush()
        db.add(SourceDocumentMetadata(source_file_id=source.id, document_number="SYN-100", payment_condition="Contado"))

        rows = _synthetic_rows()
        for row in rows:
            db.add(ProductCandidate(source_file_id=source.id, page_number=1, **row))
            desktop.products.append(SessionProduct(
                str(row["description_exact"]), str(row["presentation"]), row["quantity"], str(row["unit"]),
            ))
        db.commit()

        # Explicit synthetic expectation; this is not claimed to be an archived production output.
        expected = [
            ("LAPIZ", "unitario", 5, "un"),
            ("ZAPATO NEGRO", "caja", 3, "caja"),
            ("ZAPATO NEGRO", "pack", 2, "pack"),
        ]
        web_products = consolidate_products(db)
        desktop_products = desktop.consolidated()

        def identity(products):
            return [
                (product.description_exact, product.presentation, product.quantity, product.unit)
                for product in products
            ]

        assert identity(web_products) == expected
        assert identity(desktop_products) == expected

        assert db.query(ProductCandidate).filter_by(presentation="caja").count() == 2
        assert web_products[1].quantity == 3
        assert ProductOut(
            id=1, source_file_id=source.id, page_number=1, sku=None,
            description_exact="ZAPATO NEGRO", quantity=web_products[1].quantity,
            unit="caja", presentation="caja", observations=None,
        ).quantity == 3

        web_bodega = export_vige_pdf(
            db, tmp_path / "web-bodega.pdf", title="Lista Pickeo Bodega",
            allowed_presentations=("caja",), include_document_summary=True,
        )
        web_local = export_vige_pdf(
            db, tmp_path / "web-local.pdf", title="Lista Pickeo Local",
            allowed_presentations=("unitario", "pack"),
        )

    desktop_bodega = desktop.export(tmp_path / "desktop-bodega.pdf", "bodega")
    desktop_local = desktop.export(tmp_path / "desktop-local.pdf", "local")
    web_bodega_text = _pdf_text(web_bodega)
    web_local_text = _pdf_text(web_local)
    desktop_bodega_text = _pdf_text(desktop_bodega)
    desktop_local_text = _pdf_text(desktop_local)

    assert desktop_bodega_text == web_bodega_text
    assert desktop_local_text == web_local_text
    assert "ZAPATO NEGRO" in desktop_bodega_text
    assert "CAJA 3" in desktop_bodega_text
    assert "SYN-100" in desktop_bodega_text
    assert "LAPIZ" in desktop_local_text and "UNIDAD 5" in desktop_local_text
    assert "PACK 2" in desktop_local_text
