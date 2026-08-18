from __future__ import annotations

from decimal import Decimal

import pytest

from apex_ads.util.currency import parse_currency, parse_optional_currency, parse_percent
from apex_ads.util.text import CoercionError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("₹10,000", Decimal("10000")),
        ("Rs 10000", Decimal("10000")),
        ("INR 62,000", Decimal("62000")),
        ("10,000.00", Decimal("10000.00")),
        ("₹1,00,000", Decimal("100000")),
        (328.95, Decimal("328.95")),
        (62000, Decimal("62000")),
        ("(500)", Decimal("-500")),
    ],
)
def test_parse_currency(raw: object, expected: Decimal) -> None:
    assert parse_currency(raw) == expected


@pytest.mark.parametrize("raw", ["", "—", "abc", "₹", True])
def test_parse_currency_rejects_junk(raw: object) -> None:
    with pytest.raises(CoercionError):
        parse_currency(raw)


def test_workbook_budgets_sum_to_the_invariant() -> None:
    """The five real Stage-1 budgets add to exactly ₹62,000 — no tolerance needed."""
    budgets = ["5,000", "₹20,000", "17000", "10,000", "₹10,000"]
    assert sum(parse_currency(value) for value in budgets) == Decimal("62000")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("35%", Decimal("0.35")),
        ("0.35", Decimal("0.35")),
        (0.35, Decimal("0.35")),
        ("100%", Decimal("1")),
        (35, Decimal("0.35")),
    ],
)
def test_parse_percent(raw: object, expected: Decimal) -> None:
    assert parse_percent(raw) == expected


def test_parse_optional_currency_allows_null_tokens() -> None:
    assert parse_optional_currency("—") is None
    assert parse_optional_currency("₹50") == Decimal("50")
