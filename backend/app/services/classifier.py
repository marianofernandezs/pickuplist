from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ClassificationResult:
    presentation: str
    quantity: int | None
    unit: str | None


RULES: list[tuple[str, re.Pattern[str]]] = [
    ("caja", re.compile(r"\bcaja\s*x?\s*(\d+)\b", re.IGNORECASE)),
    ("pack", re.compile(r"\bpack\s*x?\s*(\d+)\b", re.IGNORECASE)),
    ("display", re.compile(r"\bdisplay\s*x?\s*(\d+)\b", re.IGNORECASE)),
    ("bolsa", re.compile(r"\bbolsa\s*x?\s*(\d+)\b", re.IGNORECASE)),
    ("set", re.compile(r"\bset\s*(de)?\s*(\d+)\b", re.IGNORECASE)),
    ("unitario", re.compile(r"\b(unidad|un\.|u\.)\b", re.IGNORECASE)),
]

SKU_REGEX = re.compile(r"\b(?:SKU|COD|CODIGO|C[ÓO]DIGO)[:\s-]*([A-Z0-9\-]{3,})\b", re.IGNORECASE)


def detect_sku(text: str) -> str | None:
    m = SKU_REGEX.search(text)
    return m.group(1) if m else None


def classify_presentation(text: str) -> ClassificationResult:
    normalized = " ".join(text.split())

    for label, pattern in RULES:
        m = pattern.search(normalized)
        if not m:
            continue
        quantity: int | None = None
        if label == "set":
            groups = [g for g in m.groups() if g and g.isdigit()]
            quantity = int(groups[0]) if groups else None
        elif m.groups():
            maybe_number = m.group(1)
            quantity = int(maybe_number) if maybe_number and maybe_number.isdigit() else None

        unit = "un" if label != "unitario" else "unidad"
        return ClassificationResult(presentation=label, quantity=quantity, unit=unit)

    numeric_units = re.search(r"\b(\d+)\s*(unidades|unidad|un)\b", normalized, re.IGNORECASE)
    if numeric_units:
        return ClassificationResult(presentation="pack", quantity=int(numeric_units.group(1)), unit="un")

    return ClassificationResult(presentation="ambiguo", quantity=None, unit=None)


def parse_quantity_cell(text: str) -> ClassificationResult:
    """
    Parsea la columna Cantidad de factura (ej: '1 CAJA', '5 PACK', '30 UN').
    """
    normalized = " ".join(text.upper().split())
    match = re.search(r"(\d+)", normalized)
    quantity = int(match.group(1)) if match else None

    if re.search(r"\bCAJA\b", normalized):
        return ClassificationResult(presentation="caja", quantity=quantity, unit="caja")
    if re.search(r"\bPACK\b|\bPAQ\b", normalized):
        return ClassificationResult(presentation="pack", quantity=quantity, unit="pack")
    if re.search(r"\bDISPLAY\b", normalized):
        return ClassificationResult(presentation="display", quantity=quantity, unit="display")
    if re.search(r"\bBOLSA\b", normalized):
        return ClassificationResult(presentation="bolsa", quantity=quantity, unit="bolsa")
    if re.search(r"\bSET\b", normalized):
        return ClassificationResult(presentation="set", quantity=quantity, unit="set")
    if re.search(r"\bUN\b|\bUND\b|\bUNIDAD\b|\bUNIDADES\b", normalized):
        return ClassificationResult(presentation="unitario", quantity=quantity, unit="un")

    return ClassificationResult(presentation="ambiguo", quantity=quantity, unit=None)
