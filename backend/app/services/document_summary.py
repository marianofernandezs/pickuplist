from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.entities import ExtractedLine, SourceFile
from app.services.extractor import is_registro_interno_document


@dataclass(frozen=True)
class DocumentSummary:
    number: str
    payment_condition: str


NUMBER_PATTERN = re.compile(r"\bN\s*(?:[º°]|[oO]\.?)\s*[:.]?\s*(\d+)")
DOCUMENT_HEADER = re.compile(r"FACTURA\s+ELECTR[ÓO]NICA|REGISTRO\s+INTERNO", re.IGNORECASE)
PAYMENT_LABEL = re.compile(r"Condici[oó]n(?:es)?\s+de\s+pago\s*:?\s*", re.IGNORECASE)
PAYMENT_END = re.compile(
    r"^(?:Vencimiento|Observaciones|Monto\s+Neto|IVA\b|Total\b|Subtotal\b|"
    r"Timbre\s+Electr[oó]nico|Resoluci[oó]n|SKU\b|Glosa\b|Señor\(es\)|Fecha\b|"
    r"Sistema\s+de\s+gesti[oó]n)",
    re.IGNORECASE,
)


def parse_document_summary(lines: Sequence[str]) -> DocumentSummary:
    cleaned = [" ".join(line.split()) for line in lines if line.strip()]
    text = "\n".join(cleaned)
    registry = is_registro_interno_document([text])
    header = DOCUMENT_HEADER.search(text)
    number = None
    if header:
        # Restrict the search to the document heading, excluding product codes
        # and the SII resolution number further down the page.
        heading = re.split(r"S\.I\.I\.|Señor\(es\)|Fecha\b|SKU\b|Glosa\b", text[header.end():], maxsplit=1,
                           flags=re.IGNORECASE)[0]
        number = NUMBER_PATTERN.search(heading)

    if registry:
        payment = "registro interno stock"
    else:
        payment_lines: list[str] = []
        for index, line in enumerate(cleaned):
            label = PAYMENT_LABEL.match(line)
            if label is None:
                continue
            remainder = line[label.end():].strip()
            if remainder and not PAYMENT_END.match(remainder):
                payment_lines.append(remainder)
            for value in cleaned[index + 1:]:
                if PAYMENT_END.match(value) or PAYMENT_LABEL.match(value) or DOCUMENT_HEADER.search(value):
                    break
                payment_lines.append(value)
            break
        payment = " ".join(payment_lines) or "No informada"

    return DocumentSummary(number.group(1) if number else "No identificado", payment)


def collect_document_summaries(db: Session) -> list[DocumentSummary]:
    sources = db.query(SourceFile).filter(SourceFile.status == "processed").order_by(
        SourceFile.created_at, SourceFile.id,
    ).all()
    rows = db.query(ExtractedLine).join(SourceFile).filter(SourceFile.status == "processed").order_by(
        ExtractedLine.source_file_id, ExtractedLine.page_number, ExtractedLine.block_index, ExtractedLine.id,
    ).all()
    by_source: dict[int, list[str]] = {}
    for row in rows:
        by_source.setdefault(row.source_file_id, []).extend(row.raw_text.splitlines())
    return [parse_document_summary(by_source.get(source.id, [])) for source in sources]
