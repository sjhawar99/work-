"""Currency and percentage coercion.

The workbook writes money as `₹10,000`, `Rs 10000`, `10,000.00` or a bare number, and
percentages as `35%` or `0.35`. All of them land as `Decimal`.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from apex_ads.util.text import CoercionError, is_null_token, normalise_text

_CURRENCY_SYMBOLS = re.compile(r"(?i)[₹$€£]|\brs\.?\b|\binr\b")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{2,3}\b)")
_NEGATIVE_PARENS = re.compile(r"^\((?P<body>.*)\)$")


def parse_currency(value: object) -> Decimal:
    """Coerce a money cell to `Decimal`. Raises `CoercionError` on anything else.

    Accepts Indian grouping (`₹1,00,000`), symbols, `Rs`/`INR` labels and accounting
    parentheses for negatives.
    """
    if isinstance(value, bool):
        raise CoercionError(value, "currency")
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value))

    text = normalise_text(str(value))
    negative = False
    if match := _NEGATIVE_PARENS.match(text):
        negative, text = True, match.group("body")
    text = _THOUSANDS.sub("", _CURRENCY_SYMBOLS.sub("", text)).replace(" ", "")
    if not text:
        raise CoercionError(value, "currency")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise CoercionError(value, "currency") from exc
    return -amount if negative else amount


def parse_percent(value: object) -> Decimal:
    """Coerce a percentage cell to a `Decimal` fraction: `35%` and `0.35` both give 0.35.

    A bare number greater than 1 is read as a percentage (`35` → 0.35); 1 or less is read
    as an already-computed fraction. `100%` is 1, and a bare `1` is also 1 — the two
    readings agree there, so the ambiguity is harmless.
    """
    if isinstance(value, bool):
        raise CoercionError(value, "percentage")
    text = normalise_text(str(value))
    explicit = text.endswith("%")
    if explicit:
        text = text[:-1].strip()
    if not text:
        raise CoercionError(value, "percentage")
    try:
        number = Decimal(text.replace(",", ""))
    except InvalidOperation as exc:
        raise CoercionError(value, "percentage") from exc
    return number / 100 if explicit or number > 1 else number


def parse_optional_currency(value: object) -> Decimal | None:
    """`parse_currency`, except that a null token yields `None` instead of raising."""
    return None if is_null_token(value) else parse_currency(value)
