from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.services.consolidator import consolidate_products


def export_vige_pdf(
    db: Session,
    output_path: Path,
    *,
    title: str = "Lista VIGE",
    allowed_presentations: Iterable[str] | None = None,
) -> Path:
    products = consolidate_products(db)
    if allowed_presentations is not None:
        allowed = {item.lower() for item in allowed_presentations}
        products = [product for product in products if product.presentation.lower() in allowed]

    c = canvas.Canvas(str(output_path), pagesize=A4)
    width, height = A4
    y = height - 40

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, title)
    y -= 30

    left = 40
    table_width = width - 80
    desc_col_width = table_width - 150
    qty_col_width = 150
    row_height = 18

    def draw_header(row_y: float) -> float:
        c.setFont("Helvetica-Bold", 10)
        c.rect(left, row_y - row_height, desc_col_width, row_height)
        c.rect(left + desc_col_width, row_y - row_height, qty_col_width, row_height)
        c.drawString(left + 6, row_y - 12, "Descripcion")
        c.drawString(left + desc_col_width + 6, row_y - 12, "Cantidad")
        return row_y - row_height

    y = draw_header(y)
    c.setFont("Helvetica", 9)

    for p in products:
        if y < 60:
            c.showPage()
            y = height - 40
            y = draw_header(y)
            c.setFont("Helvetica", 9)

        presentation = p.presentation.upper()
        if presentation == "UNITARIO":
            presentation = "UNIDAD"
        qty_number = str(p.quantity) if p.quantity is not None else "-"
        qty_text = f"{presentation} {qty_number}"
        desc_text = p.description_exact

        c.rect(left, y - row_height, desc_col_width, row_height)
        c.rect(left + desc_col_width, y - row_height, qty_col_width, row_height)
        c.drawString(left + 6, y - 12, desc_text[:90])
        c.drawString(left + desc_col_width + 6, y - 12, qty_text[:24])
        y -= row_height

    c.save()
    return output_path
