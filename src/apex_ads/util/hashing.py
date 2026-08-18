"""Content hashing, so every artifact is traceable to an exact input (spec §10.6)."""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, read in chunks so a large workbook does not sit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 of a string, UTF-8 encoded."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_hash(digest: str, length: int = 8) -> str:
    """First `length` characters of a hex digest, for run IDs and report headers."""
    if length < 1:
        raise ValueError("length must be positive")
    return digest[:length]
