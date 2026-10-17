from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ConsolidatedProduct:
    description_exact: str
    presentation: str
    quantity: int | None
    unit: str | None


def _normalize_description(text: str) -> str:
    upper = text.upper().strip()
    return re.sub(r"\s+", " ", upper)


def consolidate_products(db: Session) -> list[ConsolidatedProduct]:
    from app.models.entities import ProductCandidate

    rows = db.query(ProductCandidate).all()
    return consolidate_product_rows(rows)


def consolidate_product_rows(rows) -> list[ConsolidatedProduct]:
    """Apply the existing grouping, quantity sum and ordering to product rows."""

    grouped: dict[tuple[str, str], ConsolidatedProduct] = {}

    for row in rows:
        normalized_desc = _normalize_description(row.description_exact)
        key = (normalized_desc, row.presentation)

        if key not in grouped:
            grouped[key] = ConsolidatedProduct(
                description_exact=normalized_desc,
                presentation=row.presentation,
                quantity=row.quantity,
                unit=row.unit,
            )
            continue

        prev = grouped[key]
        prev_qty = prev.quantity or 0
        next_qty = row.quantity or 0
        total_qty = prev_qty + next_qty

        grouped[key] = ConsolidatedProduct(
            description_exact=prev.description_exact,
            presentation=prev.presentation,
            quantity=total_qty,
            unit=prev.unit,
        )

    return sorted(grouped.values(), key=lambda p: p.description_exact)
