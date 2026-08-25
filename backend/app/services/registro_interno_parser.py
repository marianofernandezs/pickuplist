from __future__ import annotations

import re
from typing import Any

_MONEY_PATTERN = re.compile(r"\$\s*[\d.,]+")
_SKU_PATTERN = re.compile(
    r"^(?P<sku>(?:BODEGA[A-Z0-9]+|LOCAL[A-Z0-9]+))\b\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_QUANTITY_PATTERN = re.compile(
    r"\b(?P<cantidad>\d+(?:[,.]\d+)?)\s+"
    r"(?P<presentacion>UN|CAJA|PACK|BOLSA|DISPLAY|SET|PAQ)\b",
    re.IGNORECASE,
)


def _compact(value: str) -> str:
    return " ".join(value.replace("\n", " ").split())


def _pick_quantity(matches: list[re.Match[str]]) -> re.Match[str]:
    non_unit_matches = [
        match
        for match in matches
        if match.group("presentacion").upper() not in {"UN", "UND", "UNIDAD", "UNIDADES"}
    ]
    return non_unit_matches[-1] if non_unit_matches else matches[-1]


def parseRegistroInternoBuffer(buffer: str) -> dict[str, Any] | None:
    """Parsea un buffer completo de una línea de Registro Interno."""
    normalized = _compact(buffer)
    sku_match = _SKU_PATTERN.match(normalized)
    if not sku_match:
        return None

    sku = sku_match.group("sku").upper()
    body = sku_match.group("body")
    first_money = _MONEY_PATTERN.search(body)
    quantity_zone = body[: first_money.start()] if first_money else body
    quantity_matches = list(_QUANTITY_PATTERN.finditer(quantity_zone))
    if not quantity_matches:
        return None

    quantity_match = _pick_quantity(quantity_matches)
    description = _compact(quantity_zone[: quantity_match.start()]).strip()
    if not description:
        return None

    raw_quantity = quantity_match.group("cantidad").replace(",", ".")
    quantity = float(raw_quantity) if "." in raw_quantity else int(raw_quantity)

    return {
        "sku": sku,
        "descripcion_exacta": description,
        "cantidad": quantity,
        "tipo_presentacion": quantity_match.group("presentacion").upper(),
    }


def parse_registro_interno_buffer(buffer: str) -> dict[str, Any] | None:
    """Alias snake_case para uso interno sin perder el nombre solicitado."""
    return parseRegistroInternoBuffer(buffer)
