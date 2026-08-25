from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import pdfplumber
from sqlalchemy.orm import Session

from app.models.entities import ExtractedLine, ProductCandidate, SourceFile
from app.services.classifier import detect_sku, parse_quantity_cell
from app.services.registro_interno_parser import parseRegistroInternoBuffer

REGISTRO_SKU_PATTERN = re.compile(r"^(?:BODEGA[A-Z0-9]+|LOCAL[A-Z0-9]+)\b", re.IGNORECASE)
REGISTRO_QUANTITY_PATTERN = re.compile(
    r"\b\d+(?:[,.]\d+)?\s+(?:UN|CAJA|PACK|BOLSA|DISPLAY|SET|PAQ)\b",
    re.IGNORECASE,
)
REGISTRO_QUANTITY_LINE_PATTERN = re.compile(
    r"^\d+(?:[,.]\d+)?\s+(?:UN|CAJA|PACK|BOLSA|DISPLAY|SET|PAQ)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedProduct:
    sku: str | None
    descripcion_exacta: str
    cantidad: int | float | None
    tipo_presentacion: str
    page_number: int
    unit: str | None = None
    observations: str | None = None


def _compact_text(value: str) -> str:
    return " ".join(value.replace("\n", " ").split())


def is_registro_interno_document(page_texts: list[str]) -> bool:
    document_text = _compact_text(" ".join(page_texts)).upper()
    return any(
        marker in document_text
        for marker in (
            "REGISTRO INTERNO",
            "DISMINUYE STOCK",
            "SKU GLOSA CANTIDAD",
        )
    )


def build_registro_interno_buffers(lines: list[str]) -> list[tuple[int, str]]:
    """Construye buffers desde líneas hasta encontrar cantidad y presentación."""
    buffers: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_start = 0

    def flush() -> None:
        nonlocal current_lines
        if current_lines:
            buffers.append((current_start, _compact_text(" ".join(current_lines))))
            current_lines = []

    for line_number, raw_line in enumerate(lines, start=1):
        line = _compact_text(raw_line)
        if not line:
            continue

        if REGISTRO_SKU_PATTERN.match(line):
            flush()
            current_start = line_number
            current_lines = [line]
            if REGISTRO_QUANTITY_LINE_PATTERN.match(line):
                flush()
            continue

        if not current_lines:
            continue

        current_lines.append(line)
        if REGISTRO_QUANTITY_LINE_PATTERN.match(line):
            flush()

    flush()
    return buffers


def _parsed_registry_product(parsed: dict[str, Any], page_number: int) -> ParsedProduct:
    presentation = str(parsed["tipo_presentacion"]).upper()
    return ParsedProduct(
        sku=str(parsed["sku"]),
        descripcion_exacta=str(parsed["descripcion_exacta"]),
        cantidad=parsed["cantidad"],
        tipo_presentacion=presentation,
        page_number=page_number,
        unit=presentation.lower(),
    )


def _dedupe_products(products: list[ParsedProduct]) -> list[ParsedProduct]:
    unique: list[ParsedProduct] = []
    seen: set[tuple[int, str, str, int | float | None, str]] = set()
    for product in products:
        key = (
            product.page_number,
            product.sku or "",
            product.descripcion_exacta.upper().strip(),
            product.cantidad,
            product.tipo_presentacion,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(product)
    return unique


def _merge_registry_products(
    table_products: list[ParsedProduct],
    line_products: list[ParsedProduct],
) -> list[ParsedProduct]:
    """Prefiere el buffer de líneas cuando tabla y líneas describen el mismo SKU."""
    line_identities = {
        (
            product.page_number,
            (product.sku or "").upper(),
            product.cantidad,
            product.tipo_presentacion.upper(),
        )
        for product in line_products
    }
    table_only = [
        product
        for product in table_products
        if (
            product.page_number,
            (product.sku or "").upper(),
            product.cantidad,
            product.tipo_presentacion.upper(),
        )
        not in line_identities
    ]
    return _dedupe_products(table_only + line_products)


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


def _extract_table_products(path: Path, *, registro_interno: bool) -> list[ParsedProduct]:
    products: list[ParsedProduct] = []

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

                if registro_interno:
                    for row in rows:
                        if not row:
                            continue
                        non_empty_cells = [cell.strip() for cell in row if cell and cell.strip()]
                        if not non_empty_cells:
                            continue

                        parsed = parseRegistroInternoBuffer(" ".join(non_empty_cells))
                        if parsed is not None:
                            products.append(_parsed_registry_product(parsed, page_number))
                    continue

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

                    products.append(
                        ParsedProduct(
                            sku=sku,
                            descripcion_exacta=glosa,
                            cantidad=parsed_qty.quantity,
                            tipo_presentacion=parsed_qty.presentation.upper(),
                            page_number=page_number,
                            unit=parsed_qty.unit,
                            observations=f"cantidad_original:{cantidad_raw}",
                        )
                    )

    return products


def parse_pdf(db: Session, source_file: SourceFile) -> list[ParsedProduct]:
    path = Path(source_file.stored_path)
    page_texts: list[str] = []
    lines_by_page: list[list[str]] = []
    has_selectable_text = False

    with fitz.open(path) as doc:
        source_file.page_count = doc.page_count
        for page_index, page in enumerate(doc):
            text = page.get_text("text")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            page_texts.append(text)
            lines_by_page.append(lines)

            if lines:
                has_selectable_text = True

            for block_index, line in enumerate(lines):
                db.add(
                    ExtractedLine(
                        source_file_id=source_file.id,
                        page_number=page_index + 1,
                        block_index=block_index,
                        raw_text=line,
                    )
                )
            db.flush()

    registro_interno = is_registro_interno_document(page_texts)
    table_products = _extract_table_products(path, registro_interno=registro_interno)
    products = table_products

    if registro_interno:
        line_products: list[ParsedProduct] = []
        for page_number, lines in enumerate(lines_by_page, start=1):
            for _, buffer in build_registro_interno_buffers(lines):
                parsed = parseRegistroInternoBuffer(buffer)
                if parsed is not None:
                    line_products.append(_parsed_registry_product(parsed, page_number))
        products = _merge_registry_products(table_products, line_products)

    for product in products:
        db.add(
            ProductCandidate(
                source_file_id=source_file.id,
                page_number=product.page_number,
                line_id=None,
                sku=product.sku,
                description_exact=product.descripcion_exacta,
                quantity=product.cantidad,
                unit=product.unit,
                presentation=product.tipo_presentacion.lower(),
                observations=product.observations,
            )
        )

    source_file.requires_ocr = not has_selectable_text
    source_file.status = "processed" if has_selectable_text else "requires_ocr"
    db.add(source_file)
    db.commit()
    return products
