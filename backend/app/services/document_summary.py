from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import fitz

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class DocumentSummary:
    number: str
    payment_condition: str | None


def _normalize(text: str) -> str:
    return ''.join(char for char in unicodedata.normalize('NFD', text.lower())
                   if not unicodedata.combining(char))


NUMBER_PATTERN = re.compile(r"\bN\s*(?:[º°]|[oO]\.?)\s*[:.]?\s*(\d+)")
DOCUMENT_HEADER = re.compile(r"FACTURA\s+(?:ELECTR[ÓO]NICA|EXENTA)|REGISTRO\s+INTERNO", re.IGNORECASE)
# Specific payment terms take precedence over the payment method field.
PAYMENT_LABELS = [
    re.compile(r"\bcondicion(?:es)?\s+(?:de\s+)?pago\b\s*:?\s*"),
    re.compile(r"\b(?:condicion(?:es)?\s+(?:de\s+)?venta|terminos\s+(?:de\s+)?pago)\b\s*:?\s*"),
    re.compile(r"\bforma\s+(?:de\s+)?pago\b\s*:?\s*"),
]
FIELD_LABEL = re.compile(
    r"\b(?:vencimiento|observaciones|monto\s+(?:neto|exento|total)|iva|total|subtotal|"
    r"timbre\s+electronico|resolucion|sku|glosa|cantidad|senor\(es\)|fecha|"
    r"sistema\s+de\s+gestion|vendedor|cliente|rut|direccion|giro|comuna|ciudad|"
    r"contacto|telefono|condicion(?:es)?\s+(?:de\s+)?pago|forma\s+(?:de\s+)?pago)\b"
)


def _value(text: str) -> str:
    text = ' '.join(text.split())
    normalized = _normalize(text)
    for boundary in FIELD_LABEL.finditer(normalized):
        # A word such as "total" may belong to the value itself. Only a
        # separate field delimiter should truncate an inline value.
        if (boundary.start() == 0 or normalized[boundary.end():].lstrip().startswith((':', '$'))
                or boundary.group() in ('vencimiento', 'observaciones', 'fecha')
                or boundary.group().startswith('monto ')):
            text = text[:boundary.start()].strip()
            break
    return text


def _continues(previous: str, following: str) -> bool:
    return bool(re.search(r"(?:credito|plazo|a|de|en)\s*$", _normalize(previous))
                or re.match(r"\d+\s*(?:dias|meses|cuotas)\b|^(?:dias|habiles|corridos)\b", _normalize(following)))


def _payment_from_lines(lines: list[str], labels: Sequence[re.Pattern[str]] = PAYMENT_LABELS) -> str | None:
    for label in labels:
        for index, line in enumerate(lines):
            # Labels can wrap over several lines; don't concatenate values
            # blindly because the next PDF text block may be another column.
            for length in range(1, min(3, len(lines) - index) + 1):
                combined = ' '.join(lines[index:index + length])
                match = label.search(_normalize(combined))
                if not match:
                    continue
                value = _value(combined[match.end():])
                next_index = index + length
                if not value and next_index < len(lines):
                    value = _value(lines[next_index])
                    next_index += 1
                while value and next_index < len(lines) and _continues(value, lines[next_index]):
                    continuation = _value(lines[next_index])
                    if not continuation:
                        break
                    value += ' ' + continuation
                    next_index += 1
                if value:
                    return value
                break
    return None


def parse_document_summary(lines: Sequence[str]) -> DocumentSummary:
    cleaned = [' '.join(line.split()) for line in lines if line.strip()]
    text = '\n'.join(cleaned)
    registry = bool(re.search(r"REGISTRO\s+INTERNO|DISMINUYE\s+STOCK", text, re.IGNORECASE))
    header = DOCUMENT_HEADER.search(text)
    number = None
    if header:
        heading = re.split(r"S\.I\.I\.|Señor\(es\)|Fecha\b|SKU\b|Glosa\b", text[header.end():],
                           maxsplit=1, flags=re.IGNORECASE)[0]
        number = NUMBER_PATTERN.search(heading)
    payment = 'registro interno stock' if registry else _payment_from_lines(cleaned)
    return DocumentSummary(number.group(1) if number else 'No identificado', payment)


def _payment_from_page(page: fitz.Page, labels: Sequence[re.Pattern[str]] = PAYMENT_LABELS) -> str | None:
    words = page.get_text('words')
    grouped: dict[tuple[int, int], list] = {}
    for word in words:
        grouped.setdefault((word[5], word[6]), []).append(word)
    # Search the label in the original word order; its bounding box survives
    # line breaks and independent label/value text blocks.
    for label in labels:
        for index in range(len(words)):
            for length in range(2, min(5, len(words) - index) + 1):
                span = words[index:index + length]
                if not label.fullmatch(_normalize(' '.join(word[4] for word in span))):
                    continue
                x0, y0 = min(w[0] for w in span), min(w[1] for w in span)
                x1, y1 = max(w[2] for w in span), max(w[3] for w in span)
                if y1 - y0 > 50 or x1 - x0 > 300:
                    continue
                below_limit = y1 + 45
                for group in grouped.values():
                    group_y = min(w[1] for w in group)
                    group_text = ' '.join(w[4] for w in group)
                    if (group_y >= y1 - 1 and abs(min(w[0] for w in group) - x0) <= 25
                            and FIELD_LABEL.match(_normalize(group_text))):
                        below_limit = min(below_limit, group_y)
                candidates = []
                for line_words in grouped.values():
                    remaining = [w for w in line_words if w not in span]
                    if not remaining:
                        continue
                    # Prefer a value on the right, including vertically centered
                    # values next to a label occupying two lines.
                    right = [w for w in remaining if w[0] >= x1 - 1 and
                             w[1] < y1 + 2 and w[3] > y0 - 2]
                    if right:
                        value = _value(' '.join(w[4] for w in sorted(right, key=lambda w: w[0])))
                        if value:
                            candidates.append((0, min(w[0] for w in right) - x1, value, right))
                    below = [w for w in remaining if w[1] >= y1 - 1 and w[1] < below_limit and
                             w[0] >= x0 - 5 and w[0] <= x0 + 250]
                    if below and abs(min(w[0] for w in below) - x0) <= 25:
                        value = _value(' '.join(w[4] for w in sorted(below, key=lambda w: w[0])))
                        if value:
                            candidates.append((1, min(w[1] for w in below) - y1, value, below))
                if candidates:
                    _, _, value, value_words = min(candidates, key=lambda item: item[:2])
                    value_x = min(w[0] for w in value_words)
                    value_y = max(w[3] for w in value_words)
                    for line_words in sorted(grouped.values(), key=lambda group: min(w[1] for w in group)):
                        line_y = min(w[1] for w in line_words)
                        if value_y - 3 <= line_y <= value_y + 18 and abs(min(w[0] for w in line_words) - value_x) <= 25:
                            continuation = _value(' '.join(w[4] for w in line_words))
                            if continuation and _continues(value, continuation):
                                value += ' ' + continuation
                                value_y = max(w[3] for w in line_words)
                    return value
    return None


def extract_payment_condition(document: fitz.Document) -> str | None:
    """Read Condiciones de pago with the same PyMuPDF text/word APIs as the reader.

    Coordinates associate separate columns before falling back to text lines.
    Only payment conditions qualify here; a payment-method field isn't a substitute.
    """
    labels = PAYMENT_LABELS[:1]
    for page in document:
        payment = _payment_from_page(page, labels)
        if payment is not None:
            return payment
    # Keep page boundaries so an empty field cannot consume the next page.
    for page in document:
        lines = [' '.join(line.split()) for line in page.get_text('text').splitlines() if line.strip()]
        payment = _payment_from_lines(lines, labels)
        if payment is not None:
            return payment
    return None


def extract_document_summary(document: fitz.Document) -> DocumentSummary:
    texts = [page.get_text('text') for page in document]
    summary = parse_document_summary([line for text in texts for line in text.splitlines()])
    if summary.payment_condition == 'registro interno stock':
        return summary
    return DocumentSummary(summary.number, extract_payment_condition(document))


def collect_document_summaries(db: Session) -> list[DocumentSummary]:
    from app.models.entities import ExtractedLine, SourceDocumentMetadata, SourceFile

    sources = db.query(SourceFile).filter(SourceFile.status == 'processed').order_by(
        SourceFile.created_at, SourceFile.id,
    ).all()
    cached = {row.source_file_id: row for row in db.query(SourceDocumentMetadata).all()}
    missing_ids = [source.id for source in sources if source.id not in cached]
    rows = db.query(ExtractedLine).filter(ExtractedLine.source_file_id.in_(missing_ids)).order_by(
        ExtractedLine.source_file_id, ExtractedLine.page_number, ExtractedLine.block_index, ExtractedLine.id,
    ).all()
    by_source: dict[int, list[str]] = {}
    for row in rows:
        by_source.setdefault(row.source_file_id, []).extend(row.raw_text.splitlines())
    summaries = []
    for source in sources:
        metadata = cached.get(source.id)
        if metadata is not None:
            summaries.append(DocumentSummary(metadata.document_number, metadata.payment_condition))
            continue
        # Legacy uploads have no cached metadata. Re-read their PDF when it is
        # available, falling back to persisted lines if it was removed.
        try:
            with fitz.open(Path(source.stored_path)) as document:
                summaries.append(extract_document_summary(document))
        except (OSError, fitz.FileDataError, fitz.FileNotFoundError):
            summaries.append(parse_document_summary(by_source.get(source.id, [])))
    return summaries
