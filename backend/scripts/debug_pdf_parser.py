from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import pdfplumber

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.extractor import (
    build_registro_interno_buffers,
    is_registro_interno_document,
)
from app.services.registro_interno_parser import parseRegistroInternoBuffer

PRODUCT_MARKER = "BODEGAAS54 ALCOHOL SPRAY ECOSAFE 5 LTS X 4 BIDONES"
PRODUCT_SKU_MARKER = "BODEGAAS54"


@dataclass(frozen=True)
class ProductBuffer:
    page_number: int
    table_number: int
    row_number: int
    text: str


@dataclass(frozen=True)
class BufferResult:
    buffer: ProductBuffer
    parsed: dict[str, Any] | None
    discard_reason: str | None


def _normalized_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _compact(value: str) -> str:
    return " ".join(value.replace("\n", " ").split()).upper()


def _contains_critical_product(value: str) -> bool:
    compact = _compact(value)
    return (
        PRODUCT_MARKER in compact
        or (
            PRODUCT_SKU_MARKER in compact
            and "ALCOHOL SPRAY ECOSAFE 5 LTS X 4" in compact
            and "BIDONES" in compact
        )
    )


def _detect_document_type(page_texts: list[str]) -> str:
    document_text = " ".join(page_texts).upper()
    if "REGISTRO INTERNO" in document_text and "DISMINUYE STOCK" in document_text:
        return "REGISTRO INTERNO - DISMINUYE STOCK"
    return "DESCONOCIDO"


def _make_buffers(pdf_path: Path) -> tuple[list[ProductBuffer], list[str]]:
    buffers: list[ProductBuffer] = []
    stage_reasons: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            if not tables:
                stage_reasons.append(
                    f"PAGE {page_number}: no se construyeron buffers porque extract_tables() devolvió 0 tablas."
                )
                continue

            for table_number, table in enumerate(tables, start=1):
                if not table:
                    stage_reasons.append(
                        f"PAGE {page_number} TABLE {table_number}: tabla vacía; no se construyeron buffers."
                    )
                    continue

                for row_number, row in enumerate(table[1:], start=2):
                    non_empty_cells = [cell.strip() for cell in row if cell and cell.strip()]
                    if not non_empty_cells:
                        stage_reasons.append(
                            f"PAGE {page_number} TABLE {table_number} ROW {row_number}: fila vacía; buffer descartado."
                        )
                        continue

                    if len(non_empty_cells) != 1:
                        stage_reasons.append(
                            f"PAGE {page_number} TABLE {table_number} ROW {row_number}: "
                            f"se encontraron {len(non_empty_cells)} celdas no vacías; no se construyó buffer colapsado."
                        )
                        continue

                    buffers.append(
                        ProductBuffer(
                            page_number=page_number,
                            table_number=table_number,
                            row_number=row_number,
                            text=" ".join(non_empty_cells[0].split()),
                        )
                    )

    return buffers, stage_reasons


def _parse_buffers(buffers: list[ProductBuffer]) -> list[BufferResult]:
    results: list[BufferResult] = []
    for product_buffer in buffers:
        parsed = parseRegistroInternoBuffer(product_buffer.text)
        reason = None
        if parsed is None:
            reason = (
                "No se convirtió en producto: falta SKU inicial, cantidad/presentación válida "
                "antes del precio o descripción no vacía."
            )
        results.append(BufferResult(product_buffer, parsed, reason))
    return results


def _print_page_section(title: str, page_texts: list[str], *, normalized: bool = False) -> None:
    print(f"\n=== {title} ===")
    for page_number, text in enumerate(page_texts, start=1):
        print(f"--- PAGE {page_number} ---")
        values = _normalized_lines(text) if normalized else text.rstrip().splitlines()
        if not values:
            print("(sin texto)")
            continue
        for line_number, value in enumerate(values, start=1):
            marker = " [CRITICAL PRODUCT]" if PRODUCT_SKU_MARKER in value.upper() else ""
            print(f"{line_number:03d}{marker}: {value}")


def _print_buffers(results: list[BufferResult], stage_reasons: list[str]) -> None:
    print("\n=== PRODUCT BUFFERS ===")
    if not results:
        print("(no se construyeron buffers)")
    for result in results:
        buffer = result.buffer
        marker = " [CRITICAL PRODUCT]" if _contains_critical_product(buffer.text) else ""
        print(
            f"[{buffer.page_number}:{buffer.table_number}:{buffer.row_number}]{marker} "
            f"{buffer.text}"
        )
    if stage_reasons:
        print("\n--- BUFFER STAGE REASONS ---")
        for reason in stage_reasons:
            print(f"- {reason}")


def _print_parse_results(results: list[BufferResult]) -> None:
    print("\n=== PARSE RESULT BY BUFFER ===")
    for index, result in enumerate(results, start=1):
        marker = " [CRITICAL PRODUCT]" if _contains_critical_product(result.buffer.text) else ""
        print(f"BUFFER {index}{marker}: {result.parsed!r}")

    print("\n=== DISCARD REASONS ===")
    discarded = [result for result in results if result.discard_reason]
    if not discarded:
        print("(ningún buffer fue descartado después de construirse)")
    for index, result in enumerate(discarded, start=1):
        print(f"BUFFER {index}: {result.discard_reason}")


def _print_final_products(results: list[BufferResult]) -> None:
    ordered_results = sorted(results, key=lambda result: result.buffer.table_number != 0)
    products: list[tuple[int, dict[str, Any]]] = []
    seen: set[tuple[int, str, Any, str]] = set()
    for result in ordered_results:
        if result.parsed is None:
            continue
        key = (
            result.buffer.page_number,
            str(result.parsed.get("sku") or ""),
            result.parsed.get("cantidad"),
            str(result.parsed.get("tipo_presentacion") or "").upper(),
        )
        if key in seen:
            continue
        seen.add(key)
        products.append((result.buffer.page_number, result.parsed))

    print("\n=== FINAL PRODUCTS BEFORE DATABASE ===")
    if not products:
        print("(ningún producto)")
    for index, (page_number, product) in enumerate(products, start=1):
        marker = " [CRITICAL PRODUCT]" if _contains_critical_product(str(product)) else ""
        print(f"{index:03d}{marker} PAGE {page_number}: {product!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico paso a paso del parser PDF.")
    parser.add_argument("--file", required=True, type=Path, help="Ruta al PDF dentro del contenedor.")
    args = parser.parse_args()

    pdf_path = args.file
    if not pdf_path.is_file():
        parser.error(f"No existe el archivo PDF: {pdf_path}")

    with fitz.open(pdf_path) as document:
        page_texts = [page.get_text("text") for page in document]

    print("=== DOCUMENT TYPE ===")
    print(_detect_document_type(page_texts))
    _print_page_section("RAW TEXT BY PAGE", page_texts)
    _print_page_section("NORMALIZED LINES BY PAGE", page_texts, normalized=True)

    buffers, stage_reasons = _make_buffers(pdf_path)
    if is_registro_interno_document(page_texts):
        for page_number, page_text in enumerate(page_texts, start=1):
            for line_number, buffer_text in build_registro_interno_buffers(_normalized_lines(page_text)):
                buffers.append(
                    ProductBuffer(
                        page_number=page_number,
                        table_number=0,
                        row_number=line_number,
                        text=buffer_text,
                    )
                )
        stage_reasons.append("REGISTRO INTERNO: fallback por líneas ejecutado en todas las páginas.")
    results = _parse_buffers(buffers)
    _print_buffers(results, stage_reasons)
    _print_parse_results(results)
    _print_final_products(results)

    critical_locations = {
        "raw_text": any(_contains_critical_product(text) for text in page_texts),
        "normalized_lines": any(
            _contains_critical_product(" ".join(_normalized_lines(text))) for text in page_texts
        ),
        "buffer": any(_contains_critical_product(result.buffer.text) for result in results),
        "parse_result": any(
            result.parsed is not None and _contains_critical_product(str(result.parsed)) for result in results
        ),
        "final_products": any(
            result.parsed is not None and _contains_critical_product(str(result.parsed)) for result in results
        ),
    }
    print("\n=== CRITICAL PRODUCT TRACE ===")
    print(critical_locations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
