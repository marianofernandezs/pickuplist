from __future__ import annotations

import re


_QUANTITY_TOKEN = re.compile(r"\d+(?:[.,]\d+)?")


class InvalidProductQuantity(ValueError):
    """A product quantity is fractional or uses an ambiguous separator."""

    def __init__(
        self,
        description: str,
        quantity: str,
        *,
        document: str | None = None,
        ambiguous: bool = False,
    ) -> None:
        self.description = description.strip() or "(sin descripción)"
        self.quantity = quantity
        self.document = document
        self.ambiguous = ambiguous
        super().__init__(self._message())

    def for_document(self, document: str) -> "InvalidProductQuantity":
        return InvalidProductQuantity(
            self.description,
            self.quantity,
            document=document,
            ambiguous=self.ambiguous,
        )

    def _message(self) -> str:
        prefix = f"Documento rechazado ({self.document}): " if self.document else "Documento rechazado: "
        if self.ambiguous:
            detail = (
                f'el producto "{self.description}" contiene una cantidad ambigua '
                f"({self.quantity}). No se interpretan separadores como miles; "
                "solo se permiten cantidades enteras sin separadores."
            )
        else:
            detail = (
                f'el producto "{self.description}" contiene una cantidad decimal inválida '
                f"({self.quantity}). Solo se permiten cantidades enteras."
            )
        return prefix + detail


def parse_integer_quantity(raw_value: str, description: str) -> int | None:
    """Parse a quantity field without truncating or guessing separator meaning.

    A quantity written with a decimal separator is rejected, including values
    such as ``1.000`` whose intended decimal/thousands meaning is ambiguous.
    Numbers elsewhere in the product description are never passed here.
    """
    match = _QUANTITY_TOKEN.search(raw_value)
    if match is None:
        return None

    token = match.group(0)
    if "," in token or "." in token:
        fractional = token.split(",", 1)[-1].split(".", 1)[-1]
        # Digits after a decimal mark that are not all zero indicate a
        # fractional value. Zero suffixes are rejected as ambiguous syntax.
        ambiguous = bool(fractional) and set(fractional) == {"0"}
        raise InvalidProductQuantity(description, token, ambiguous=ambiguous)
    return int(token)


def validate_integer_quantity(value: int | float | None, description: str) -> None:
    """Guard extracted products against non-integral quantities from parsers."""
    if value is None or isinstance(value, int):
        return
    if isinstance(value, float) and value.is_integer():
        raise InvalidProductQuantity(description, str(value), ambiguous=True)
    raise InvalidProductQuantity(description, str(value))
