"""PII masking for generated reports.

Search queries can contain phone numbers, email addresses and patient-identifying text,
and the Watchdog persists reports. Everything human-readable that this tool generates
passes through here first (spec §16.1).

Raw search-term CSVs in `input/` and the analysis CSVs in `output/` are exempt — both are
git-ignored, and the operator needs the original query to review it.
"""

from __future__ import annotations

import re

PHONE_MASK = "[phone]"
EMAIL_MASK = "[email]"

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# +91 98765 43210, 098765-43210, 9876543210 — 7+ digits with optional separators.
_PHONE = re.compile(r"(?<![\w])\+?\d[\d\s().-]{5,}\d(?![\w])")


def _digit_count(text: str) -> int:
    return sum(character.isdigit() for character in text)


def redact(text: str) -> str:
    """Mask email- and phone-shaped substrings. Everything else is left alone."""
    masked = _EMAIL.sub(EMAIL_MASK, text)
    return _PHONE.sub(
        lambda match: PHONE_MASK if _digit_count(match.group()) >= 7 else match.group(),
        masked,
    )


def contains_pii(text: str) -> bool:
    """True when `redact` would change the text. Used by the guardrail tests."""
    return redact(text) != text
