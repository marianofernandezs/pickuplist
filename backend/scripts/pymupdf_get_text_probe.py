"""Small offline reproduction of Pick List's PyMuPDF text-extraction path.

The PDF is generated deterministically at runtime and contains no user data.
The script intentionally exercises the same summary and page-text calls used
by ``extract_pdf`` while printing flushed markers around each operation.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pymupdf

# Make the existing service importable when this file is run as a standalone
# script from ``backend/scripts``.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.document_summary import extract_document_summary  # noqa: E402


def begin(stage: str) -> None:
    print(f"[probe] {stage}: start", flush=True)


def done(stage: str) -> None:
    print(f"[probe] {stage}: done", flush=True)


def main() -> int:
    print(f"[probe] Python {sys.version.split()[0]}", flush=True)
    print(f"[probe] PyMuPDF {pymupdf.VersionBind}", flush=True)

    with tempfile.TemporaryDirectory(prefix="pick-list-pymupdf-probe-") as tmp:
        pdf_path = Path(tmp) / "synthetic-invoice.pdf"
        begin("create synthetic PDF")
        source = pymupdf.open()
        done("create synthetic PDF")
        begin("create PDF page")
        page = source.new_page()
        done("create PDF page")
        begin("insert synthetic invoice text")
        lines = (
            "FACTURA ELECTRONICA",
            "N° 123456",
            "Condicion de pago: CREDITO 30 DIAS",
            "PRODUCTO DE PRUEBA",
            "Cantidad 1",
        )
        for line_index, line in enumerate(lines):
            page.insert_text((54, 72 + line_index * 18), line, fontsize=12)
        done("insert synthetic invoice text")
        begin("save synthetic PDF")
        source.save(pdf_path)
        done("save synthetic PDF")
        begin("close generated document")
        source.close()
        done("close generated document")

        begin("open synthetic PDF")
        document = pymupdf.open(pdf_path)
        done("open synthetic PDF")
        try:
            page = document[0]
            begin("page 1 direct get_text('text')")
            page.get_text("text")
            done("page 1 direct get_text('text')")
            begin("page 1 direct get_text('words')")
            page.get_text("words")
            done("page 1 direct get_text('words')")

            begin("extract_document_summary (text + words APIs)")
            summary = extract_document_summary(document)
            done("extract_document_summary (text + words APIs)")
            print(f"[probe] summary: {summary!r}", flush=True)

            for index, extracted_page in enumerate(document, start=1):
                stage = f"page {index} get_text('text')"
                begin(stage)
                text = extracted_page.get_text("text")
                done(stage)
                print(f"[probe] page {index} text chars: {len(text)}", flush=True)

                stage = f"page {index} cropbox"
                begin(stage)
                cropbox = extracted_page.cropbox
                done(stage)
                stage = f"page {index} Rect(cropbox) / util_make_rect"
                begin(stage)
                rect = pymupdf.Rect(cropbox)
                done(stage)
                print(f"[probe] page {index} rect: {rect!r}", flush=True)
        finally:
            begin("close input PDF")
            document.close()
            done("close input PDF")

    print("[probe] completed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
