"""Header and banner normalisation, driven by `workbook_schema.yaml → matching`.

Both sides of every comparison pass through the same `Normaliser`, so matching is
symmetric whatever the options say. The options are real: `strip_punctuation: false`
keeps `#` and `Recurring?` as distinguishable headings, which a blanket strip would
flatten to nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from apex_ads.models.config import SchemaMatching
from apex_ads.util.text import normalise_text

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Normaliser:
    """Turns a heading into a comparison key according to the schema's matching rules."""

    case_sensitive: bool = False
    collapse_whitespace: bool = True
    strip_punctuation: bool = False

    @classmethod
    def from_schema(cls, matching: SchemaMatching) -> Normaliser:
        return cls(
            case_sensitive=matching.case_sensitive,
            collapse_whitespace=matching.collapse_whitespace,
            strip_punctuation=matching.strip_punctuation,
        )

    def key(self, text: str) -> str:
        value = normalise_text(text)
        if self.strip_punctuation:
            value = _PUNCTUATION.sub(" ", value)
        if self.collapse_whitespace:
            value = _WHITESPACE.sub(" ", value).strip()
        return value if self.case_sensitive else value.casefold()
