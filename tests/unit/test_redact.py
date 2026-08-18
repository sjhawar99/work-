from __future__ import annotations

import pytest

from apex_ads.util.redact import contains_pii, redact


@pytest.mark.parametrize(
    "raw",
    [
        "call me on +91 98765 43210",
        "ring 098765-43210 please",
        "9876543210",
        "contact (0141) 123 4567",
    ],
)
def test_phone_numbers_are_masked(raw: str) -> None:
    assert "[phone]" in redact(raw)
    assert contains_pii(raw)


def test_emails_are_masked() -> None:
    assert redact("write to patient.name@example.com now") == "write to [email] now"


def test_ordinary_search_terms_survive_untouched() -> None:
    term = "knee replacement cost in jaipur"
    assert redact(term) == term
    assert not contains_pii(term)


def test_short_number_sequences_are_not_masked() -> None:
    assert redact("top 10 hospitals 2026") == "top 10 hospitals 2026"


def test_mixed_content_masks_only_the_pii() -> None:
    masked = redact("apex hospital 9876543210 admin@apexhospitals.com jaipur")
    assert masked == "apex hospital [phone] [email] jaipur"
