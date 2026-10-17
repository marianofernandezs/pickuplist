from __future__ import annotations

import fitz

from app.services.consolidator import consolidate_product_rows
from app.services.pdf_exporter import export_vige_products
from app.services.extractor import ParsedProduct


def test_local_consolidation_preserves_duplicate_summing_and_sort_order() -> None:
    products = [
        ParsedProduct("x", "  ZAPATO   NEGRO ", 2, "PACK", 1, "pack"),
        ParsedProduct("x", "zapato negro", 3, "PACK", 2, "pack"),
        ParsedProduct("y", "BOLSA", 1, "CAJA", 1, "caja"),
        ParsedProduct("x", "zapato negro", 4, "CAJA", 3, "caja"),
    ]
    # Adapt the parser records to the existing consolidation record interface.
    rows = [type("Row", (), {"description_exact": p.descripcion_exacta,
                              "presentation": p.tipo_presentacion.lower(),
                              "quantity": p.cantidad, "unit": p.unit})() for p in products]
    consolidated = consolidate_product_rows(rows)
    assert [(p.description_exact, p.presentation, p.quantity, p.unit) for p in consolidated] == [
        ("BOLSA", "caja", 1, "caja"),
        ("ZAPATO NEGRO", "pack", 5, "pack"),
        ("ZAPATO NEGRO", "caja", 4, "caja"),
    ]


def test_desktop_exports_keep_original_titles_filters_and_document_summary(tmp_path) -> None:
    rows = [
        type("Row", (), {"description_exact": "BOLSA", "presentation": "caja", "quantity": 2, "unit": "caja"})(),
        type("Row", (), {"description_exact": "VASO", "presentation": "pack", "quantity": 3, "unit": "pack"})(),
        type("Row", (), {"description_exact": "LAPIZ", "presentation": "unitario", "quantity": 8, "unit": "un"})(),
    ]
    bodega = export_vige_products(rows, tmp_path / "bodega.pdf", title="Lista Pickeo Bodega",
                                  allowed_presentations=("caja",),
                                  document_summaries=[type("Summary", (), {"number": "123", "payment_condition": "30 días"})()],
                                  include_document_summary=True)
    local = export_vige_products(rows, tmp_path / "local.pdf", title="Lista Pickeo Local",
                                 allowed_presentations=("unitario", "pack"))
    with fitz.open(bodega) as pdf:
        bodega_text = " ".join(page.get_text() for page in pdf)
    with fitz.open(local) as pdf:
        local_text = " ".join(page.get_text() for page in pdf)
    assert "Lista Pickeo Bodega" in bodega_text and "BOLSA" in bodega_text
    assert "Codigo de facturas escaneadas" in bodega_text and "123" in bodega_text
    assert "30 DÍAS" in bodega_text
    assert "VASO" not in bodega_text and "LAPIZ" not in bodega_text
    assert "Lista Pickeo Local" in local_text and "VASO" in local_text and "LAPIZ" in local_text
    assert "BOLSA" not in local_text
    assert "Codigo de facturas escaneadas" not in local_text
