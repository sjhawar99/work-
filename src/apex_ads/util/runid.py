"""Run identifiers: `YYYYMMDD-HHMMSS-<short workbook hash>` (spec §10.4).

Timestamps are UTC. Two runs from the same workbook are visibly related, and no run ever
overwrites another.
"""

from __future__ import annotations

from datetime import datetime, timezone

from apex_ads.util.hashing import short_hash


def make(workbook_sha256: str, *, now: datetime | None = None) -> str:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{moment:%Y%m%d-%H%M%S}-{short_hash(workbook_sha256)}"
