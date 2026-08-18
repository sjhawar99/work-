from __future__ import annotations

import pytest

from apex_ads.util.text import (
    CoercionError,
    is_null_token,
    normalise_key,
    normalise_text,
    parse_bool,
    tokenise,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  knee   replacement  ", "knee replacement"),
        ("knee\u200breplacement", "kneereplacement"),
        ("\ufb01le", "file"),
        ("Apex\u00a0Hospitals", "Apex Hospitals"),
    ],
)
def test_normalise_text(raw: str, expected: str) -> None:
    assert normalise_text(raw) == expected


def test_normalise_text_preserves_case() -> None:
    assert normalise_text("Book an Apex Appointment") == "Book an Apex Appointment"


@pytest.mark.parametrize(
    "variant",
    ["Net Daily Budget", "net daily budget", "Net  Daily  Budget ", "NET-DAILY-BUDGET"],
)
def test_normalise_key_agrees_across_variants(variant: str) -> None:
    assert normalise_key(variant) == "net daily budget"


def test_tokenise_strips_punctuation_and_case() -> None:
    assert tokenise("Knee-Replacement, Jaipur!") == ["knee", "replacement", "jaipur"]


@pytest.mark.parametrize("token", [None, "", "—", "-", "n/a", "  N/A  "])
def test_is_null_token(token: object) -> None:
    assert is_null_token(token) is True


def test_is_null_token_rejects_real_values() -> None:
    assert is_null_token("Account") is False
    assert is_null_token(0) is False


@pytest.mark.parametrize("raw", ["Y", "yes", "TRUE", "1", "✅", True])
def test_parse_bool_true(raw: object) -> None:
    assert parse_bool(raw) is True


@pytest.mark.parametrize("raw", ["N", "no", "FALSE", "0", "off", False])
def test_parse_bool_false(raw: object) -> None:
    assert parse_bool(raw) is False


def test_parse_bool_rejects_ambiguous_value() -> None:
    with pytest.raises(CoercionError) as excinfo:
        parse_bool("maybe")
    assert "maybe" in str(excinfo.value)
