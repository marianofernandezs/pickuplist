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


def _strip_leading_sku_token(row_text: str, assume_present: bool) -> tuple[str | None, str]:
    normalized = " ".join(row_text.replace("\n", " ").split())
    if not normalized:
        return None, normalized

    parts = normalized.split(" ", 1)
    first = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    first_upper = first.upper()

    if not rest:
        return None, normalized

    if first_upper in {"SKU", "GLOSA", "CANTIDAD"}:
        return None, normalized
    if re.search(r"^\$|^\d+$", first_upper):
        return None, normalized

    is_token_like_code = re.fullmatch(r"[A-Z0-9\-_/\.]+", first_upper) is not None
    if not is_token_like_code:
        return None, normalized

    if assume_present:
        return first_upper, rest

    if any(ch.isdigit() for ch in first_upper):
        return first_upper, rest

    return None, normalized


def _parse_collapsed_product_row(row_text: str, assume_leading_sku: bool) -> tuple[str | None, str, str] | None:
    sku, candidate_text = _strip_leading_sku_token(row_text, assume_present=assume_leading_sku)
    parsed = _parse_collapsed_glosa_cell(candidate_text)
    if not parsed:
        return None

    glosa, cantidad = parsed
    detected_sku = sku or detect_sku(glosa)
    return detected_sku, glosa, cantidad


def _is_excluded_glosa(glosa: str) -> bool:
    glosa_upper = glosa.upper()
    return any(
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
            "OBSERVACIONES",
            "SISTEMA DE GESTION",
        )
    )


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
        last_header_indexes: tuple[int, int] | None = None
        has_sku_header = False

        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue

                current_header_indexes = _find_header_indexes(table[0])
                if current_header_indexes:
                    last_header_indexes = current_header_indexes
                    header_cells = [_norm_header(cell) if cell else "" for cell in table[0]]
                    has_sku_header = any("sku" in cell for cell in header_cells)
                    rows = table[1:]
                else:
                    rows = table

                glosa_idx: int | None = None
                cantidad_idx: int | None = None
                if last_header_indexes:
                    glosa_idx, cantidad_idx = last_header_indexes

                for row in rows:
                    if not row:
                        continue

                    non_empty_cells = [cell.strip() for cell in row if cell and cell.strip()]
                    if not non_empty_cells:
                        continue

                    sku: str | None = None
                    glosa = ""
                    cantidad_raw = ""

                    # Caso colapsado: la fila completa viene en una sola celda.
                    if len(non_empty_cells) == 1:
                        parsed = _parse_collapsed_product_row(
                            non_empty_cells[0],
                            assume_leading_sku=has_sku_header,
                        )
                        if not parsed:
                            continue
                        sku, glosa, cantidad_raw = parsed
                    elif glosa_idx is not None and cantidad_idx is not None:
                        if glosa_idx >= len(row) or cantidad_idx >= len(row):
                            continue
                        glosa = (row[glosa_idx] or "").strip()
                        cantidad_raw = (row[cantidad_idx] or "").strip()

                        if glosa and not cantidad_raw:
                            collapsed = _parse_collapsed_product_row(
                                glosa,
                                assume_leading_sku=has_sku_header,
                            )
                            if collapsed:
                                sku, glosa, cantidad_raw = collapsed

                    if not glosa or not cantidad_raw:
                        continue

                    if _is_excluded_glosa(glosa):
                        continue

                    parsed_qty = parse_quantity_cell(cantidad_raw)
                    if sku is None:
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
