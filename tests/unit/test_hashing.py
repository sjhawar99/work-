from __future__ import annotations

from pathlib import Path

import pytest

from apex_ads.util.hashing import sha256_file, sha256_text, short_hash

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_text_matches_known_value() -> None:
    assert sha256_text("") == EMPTY_SHA256


def test_sha256_file_matches_text(tmp_path: Path) -> None:
    path = tmp_path / "workbook.xlsx"
    path.write_bytes(b"apex")
    assert sha256_file(path) == sha256_text("apex")


def test_sha256_file_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"x" * (1 << 21))
    assert sha256_file(path) == sha256_file(path)


def test_short_hash() -> None:
    assert short_hash(EMPTY_SHA256) == "e3b0c442"
    assert short_hash(EMPTY_SHA256, 12) == "e3b0c44298fc"


def test_short_hash_rejects_zero_length() -> None:
    with pytest.raises(ValueError, match="positive"):
        short_hash(EMPTY_SHA256, 0)
