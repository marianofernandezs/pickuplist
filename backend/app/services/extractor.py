from __future__ import annotations

from pathlib import Path
import re

import fitz
import pdfplumber
from sqlalchemy.orm import Session

from app.models.entities import ExtractedLine, ProductCandidate, SourceFile
from app.services.classifier import detect_sku, parse_quantity_cell


def _norm_header(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace(".", "")
    normalized = normalized.replace("ó", "o")
    return re.sub(r"\s+", " ", normalized)


def _find_header_indexes(row: list[str | None]) -> tuple[int, int] | None:
    normalized_cells = [_norm_header(cell) if cell else "" for cell in row]
    glosa_idx = -1
    cantidad_idx = -1

    for idx, cell in enumerate(normalized_cells):
        if "glosa" in cell:
            glosa_idx = idx
        if "cantidad" in cell:
            cantidad_idx = idx

    if glosa_idx >= 0 and cantidad_idx >= 0:
        return glosa_idx, cantidad_idx
    return None


def _parse_collapsed_glosa_cell(cell_text: str) -> tuple[str, str] | None:
    """
    Caso DTE observado: toda la fila de producto llega en la columna Glosa.
    Ejemplo:
    'PLATO ... 20 PACK $2.092,44 SI $41.849'
    """
    normalized = " ".join(cell_text.replace("\n", " ").split())
    money_matches = list(re.finditer(r"\$\s*[\d\.\,]+", normalized, flags=re.IGNORECASE))

    # En DTE colapsado, la cantidad de compra suele ir antes del precio unitario.
    # Además, fragmentos de la glosa pueden aparecer después de los montos.
    quantity_pattern = re.compile(
        r"(?P<cantidad>\d+\s*(?:CAJA|PACK|PAQ|UNIDAD(?:ES)?|UN|UND|DISPLAY|BOLSA|SET))",
        flags=re.IGNORECASE,
    )

    def pick_quantity(candidates: list[re.Match[str]]) -> re.Match[str]:
        grouped = [
            m
            for m in candidates
            if not re.search(r"\bUNIDAD(?:ES)?\b|\bUN\b|\bUND\b", m.group("cantidad"), re.IGNORECASE)
        ]
        return grouped[-1] if grouped else candidates[-1]

    if money_matches:
        first_money_start = money_matches[0].start()
        last_money_end = money_matches[-1].end()
        before_price = normalized[:first_money_start].strip()
        after_amounts = normalized[last_money_end:].strip()
        before_price = re.sub(r"\bSI\b", "", before_price, flags=re.IGNORECASE)
        before_price = re.sub(r"\s+", " ", before_price).strip()
        after_amounts = re.sub(r"\bSI\b", "", after_amounts, flags=re.IGNORECASE)
        after_amounts = re.sub(r"\s+", " ", after_amounts).strip()

        before_candidates = list(quantity_pattern.finditer(before_price))
        if before_candidates:
            quantity_match = pick_quantity(before_candidates)
            cantidad = quantity_match.group("cantidad").strip()
            glosa_before = (
                before_price[: quantity_match.start()] + " " + before_price[quantity_match.end() :]
            ).strip()
            glosa = f"{glosa_before} {after_amounts}".strip()
            glosa = re.sub(r"\s+", " ", glosa).strip()
            if glosa and cantidad:
                return glosa, cantidad

        candidate_zone = f"{before_price} {after_amounts}".strip()
    else:
        candidate_zone = normalized

    candidate_zone = re.sub(r"\bSI\b", "", candidate_zone, flags=re.IGNORECASE)
    candidate_zone = re.sub(r"\s+", " ", candidate_zone).strip()
    candidates = list(quantity_pattern.finditer(candidate_zone))
    if not candidates:
        return None

    quantity_match = pick_quantity(candidates)
    cantidad = quantity_match.group("cantidad").strip()
    glosa = (candidate_zone[: quantity_match.start()] + " " + candidate_zone[quantity_match.end() :]).strip()
    glosa = re.sub(r"\s+", " ", glosa).strip()

    if not glosa or not cantidad:
        return None
    return glosa, cantidad


def parse_pdf(db: Session, source_file: SourceFile) -> None:
    path = Path(source_file.stored_path)
    doc = fitz.open(path)
    source_file.page_count = doc.page_count

    has_selectable_text = False

    for page_index in range(doc.page_count):
        page = doc[page_index]
        text = page.get_text("text")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        if lines:
            has_selectable_text = True

        for idx, line in enumerate(lines):
            extracted = ExtractedLine(
                source_file_id=source_file.id,
                page_number=page_index + 1,
                block_index=idx,
                raw_text=line,
            )
            db.add(extracted)
        db.flush()

    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                header_indexes = _find_header_indexes(table[0])
                if not header_indexes:
                    continue

                glosa_idx, cantidad_idx = header_indexes
                for row in table[1:]:
                    if not row:
                        continue
                    if glosa_idx >= len(row) or cantidad_idx >= len(row):
                        continue

                    glosa = (row[glosa_idx] or "").strip()
                    cantidad_raw = (row[cantidad_idx] or "").strip()

                    if glosa and not cantidad_raw:
                        collapsed = _parse_collapsed_glosa_cell(glosa)
                        if collapsed:
                            glosa, cantidad_raw = collapsed

                    if not glosa or not cantidad_raw:
                        continue

                    # Excluye líneas administrativas o de totales.
                    glosa_upper = glosa.upper()
                    if any(
                        token in glosa_upper
                        for token in (
                            "TOTAL",
                            "SUBTOTAL",
                            "NETO",
                            "IVA",
                            "DESCUENTO",
                            "PAGO",
                            "CLIENTE",
                            "PROVEEDOR",
                        )
                    ):
                        continue

                    parsed_qty = parse_quantity_cell(cantidad_raw)
                    sku = detect_sku(glosa)

                    db.add(
                        ProductCandidate(
                            source_file_id=source_file.id,
                            page_number=page_number,
                            line_id=None,
                            sku=sku,
                            description_exact=glosa,
                            quantity=parsed_qty.quantity,
                            unit=parsed_qty.unit,
                            presentation=parsed_qty.presentation,
                            observations=f"cantidad_original:{cantidad_raw}",
                        )
                    )

    source_file.requires_ocr = not has_selectable_text
    source_file.status = "processed" if has_selectable_text else "requires_ocr"
    db.add(source_file)
    db.commit()
