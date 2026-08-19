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


def hash_tree(directory: Path, *, exclude: str | None = None) -> list[dict[str, object]]:
    """Every file under `directory`, by path relative to it, with size and digest.

    Recursive, and that is the whole point. Both manifests used to walk with `iterdir()`,
    which is fine right up until an output moves into a subdirectory — and one had:
    `writeback/01_ACTIONS_append.csv` and `writeback/HOW_TO_PASTE.txt` were absent from the
    audit fingerprint while every flat file beside them was covered. The files a person is
    told to paste into the operating system were the only outputs nothing vouched for.

    Keys are relative POSIX paths rather than bare names, so two files with the same name in
    different subdirectories stay distinguishable, and sorted so the manifest is stable.
    """
    entries = [
        path
        for path in directory.rglob("*")
        if path.is_file() and (exclude is None or path.name != exclude or path.parent != directory)
    ]
    return [
        {
            "name": path.relative_to(directory).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(entries)
    ]
