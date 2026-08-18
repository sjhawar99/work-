"""Run identifiers: `YYYYMMDD-HHMMSS-<short workbook hash>` (spec §10.4).

Timestamps are UTC. Two runs from the same workbook are visibly related, and no run ever
overwrites another.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from apex_ads.util.hashing import short_hash


def make(workbook_sha256: str, *, now: datetime | None = None) -> str:
    """A run identifier that cannot collide with another run of the same workbook.

    Second resolution plus the workbook hash was not enough: two builds of one workbook in
    the same second produced the same ID, and the build then made room by deleting the
    existing directory. The guarantee "no run ever overwrites another" was implemented by
    an overwrite. Microseconds plus a random suffix make collision practically impossible,
    and the build now refuses to touch an existing run directory regardless.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    unique = uuid4().hex[:6]
    return f"{moment:%Y%m%d-%H%M%S}-{moment.microsecond:06d}-{short_hash(workbook_sha256)}-{unique}"
