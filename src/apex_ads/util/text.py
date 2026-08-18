"""Text normalisation and coercion helpers.

Every value that crosses the workbook boundary passes through here. Coercion is explicit
and total: anything unparseable raises `CoercionError` naming the offending value, never
a silent `NaN` (spec §4.3 item 7).
"""

from __future__ import annotations

import re
import unicodedata

ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)

NULL_TOKENS = frozenset({"", "-", "—", "–", "n/a", "na", "none", "null"})  # noqa: RUF001

TRUE_TOKENS = frozenset({"y", "yes", "true", "t", "1", "on", "✅"})
FALSE_TOKENS = frozenset({"n", "no", "false", "f", "0", "off", "❌"})

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)


class CoercionError(ValueError):
    """A cell value could not be coerced to the expected type."""

    def __init__(self, value: object, target: str) -> None:
        self.value = value
        self.target = target
        super().__init__(f"cannot read {value!r} as {target}")


def normalise_text(value: str) -> str:
    """NFKC-normalise, strip zero-width characters, collapse whitespace, trim.

    Case is preserved — ad copy is never re-cased.
    """
    text = unicodedata.normalize("NFKC", value).translate(ZERO_WIDTH)
    return _WHITESPACE.sub(" ", text).strip()


def normalise_key(value: str) -> str:
    """Normalise a header or lookup key: case-folded, punctuation-stripped, collapsed.

    `Net Daily Budget`, `net daily budget` and `Net  Daily  Budget ` all agree.
    """
    text = _PUNCTUATION.sub(" ", normalise_text(value))
    return _WHITESPACE.sub(" ", text).strip().casefold()


def tokenise(value: str) -> list[str]:
    """Split into comparison tokens: lower-cased, punctuation-stripped, whitespace-split.

    Used by the negative-collision engine (spec §9.5). No plural or close-variant
    expansion — negatives do not match close variants.
    """
    return normalise_key(value).split()


def is_null_token(value: object) -> bool:
    """True when a cell means "nothing", including the workbook's em-dash placeholder."""
    if value is None:
        return True
    return normalise_text(str(value)).casefold() in NULL_TOKENS


def parse_bool(value: object) -> bool:
    """Coerce a workbook truthiness cell to `bool`. Raises on anything ambiguous."""
    if isinstance(value, bool):
        return value
    token = normalise_text(str(value)).casefold()
    if token in TRUE_TOKENS:
        return True
    if token in FALSE_TOKENS:
        return False
    raise CoercionError(value, "boolean")
