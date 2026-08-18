"""Frozen policy constants.

These are the transformations locked in `DECISIONS.md`. They live in Python, not config,
precisely so that no YAML edit can change them (spec §8.4).
"""

from __future__ import annotations

from typing import Final

MODIFIED_BROAD_ALIASES: Final[frozenset[str]] = frozenset(
    {"modified broad", "broad match modifier", "bmm", "modified broad match"}
)
"""Decision A3: legacy Broad Match Modifier normalises to PHRASE.

There is deliberately no config key for this mapping, so it can never be pointed at
BROAD. The `KW-008` warning that reports each normalisation is a Phase 3 validator; the
mapping itself happens at parse time so that legacy nomenclature does not break ingest.
"""

MATCH_TYPES: Final[dict[str, str]] = {
    "exact": "EXACT",
    "phrase": "PHRASE",
    "broad": "BROAD",
}

WAIVABLE_RULE_IDS: Final[frozenset[str]] = frozenset()
"""Stage 1: no rule is waivable (Decision A2, spec §9.9). Widening this is a code review."""
