from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.textsplit import wordSplit
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.services.consolidator import consolidate_products
from app.services.document_summary import DocumentSummary, collect_document_summaries


def _wrap_summary_text(value: str, width: float) -> list[str]:
    lines: list[str] = []
    for line in simpleSplit(value, "Helvetica", 9, width):
        if stringWidth(line, "Helvetica", 9) > width:
            lines.extend(part for _, part in wordSplit(line, width, "Helvetica", 9))
        else:
            lines.append(line)
    return lines or [""]


def _draw_document_summary(c: canvas.Canvas, documents: list[DocumentSummary]) -> None:
    width, height = A4
    left = 40
    column_widths = (170, width - 80 - 170)
    line_height = 12
    padding = 6

    def new_page() -> float:
        c.showPage()
        c.setFont("Helvetica-Bold", 14)
        c.drawString(left, height - 40, "Codigo de facturas escaneadas")
        y = height - 70
        c.setFont("Helvetica-Bold", 10)
        x = left
        for label, col_width in zip(("Número de documento", "Condición de pago / Tipo"), column_widths):
            c.rect(x, y - 22, col_width, 22)
            c.drawString(x + padding, y - 15, label)
            x += col_width
        return y - 22

    y = new_page()
    if not documents:
        c.setFont("Helvetica", 9)
        c.drawString(left + padding, y - 18, "Sin documentos procesados")
        y -= 24

    for document_index, document in enumerate(documents):
        # Keep the total together with the final row, including when a long
        # condition needs to continue on another page.
        bottom = 74 if document_index == len(documents) - 1 else 40
        cells = [_wrap_summary_text(value, col_width - 2 * padding)
                 for value, col_width in zip((document.number, document.payment_condition or "No informada"), column_widths)]
        line_count = max(map(len, cells))
        row_height = line_count * line_height + 2 * padding
        if y - row_height < bottom:
            y = new_page()
        offset = 0
        # Very long conditions can span pages without clipping or losing text.
        while offset < line_count:
            available_lines = int((y - bottom - 2 * padding) // line_height)
            if available_lines < 1:
                y = new_page()
                continue
            count = min(line_count - offset, available_lines)
            segment_height = count * line_height + 2 * padding
            c.setFont("Helvetica", 9)
            x = left
            for cell, col_width in zip(cells, column_widths):
                c.rect(x, y - segment_height, col_width, segment_height)
                for index, line in enumerate(cell[offset:offset + count]):
                    c.drawString(x + padding, y - padding - 9 - index * line_height, line)
                x += col_width
            y -= segment_height
            offset += count
            if offset < line_count:
                y = new_page()

    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, y - 28, f"Total facturas: {len(documents)}")


def export_vige_pdf(
    db: Session,
    output_path: Path,
    *,
    title: str = "Lista VIGE",
    allowed_presentations: Iterable[str] | None = None,
    include_document_summary: bool = False,
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

    if include_document_summary:
        _draw_document_summary(c, collect_document_summaries(db))

    c.save()
    return output_path
