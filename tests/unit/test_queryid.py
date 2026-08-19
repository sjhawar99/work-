"""The keyed query identifier (Phase-6 task zero).

Two properties have to hold at once, and they pull against each other: the same query must
produce the same handle next Friday, and somebody holding a report must not be able to
confirm a guessed phrase. These tests assert both, plus that the secret never reaches a
rendering.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from apex_ads.util.queryid import (
    ID_PREFIX,
    KEY_BYTES,
    QueryIdKey,
    QueryKeyError,
    key_notice,
    load_or_create,
    normalise_query,
    resolve,
)
from apex_ads.util.searchterm import SearchTerm

QUERY = "kidney failure last stage how long to live"


@pytest.fixture()
def key(tmp_path: Path) -> QueryIdKey:
    made, _ = load_or_create(tmp_path / "query_id.key")
    return made


def test_a_key_is_created_on_first_use_and_reused_after(tmp_path: Path) -> None:
    """The operator must not need key management explained before Friday works."""
    path = tmp_path / "sub" / "query_id.key"
    first, created = load_or_create(path)
    assert created is True
    assert path.is_file()

    again, created_again = load_or_create(path)
    assert created_again is False
    assert first.identify(QUERY) == again.identify(QUERY)


def test_a_created_key_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "query_id.key"
    load_or_create(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0, oct(mode)


def test_the_same_query_gets_the_same_id_across_runs(key: QueryIdKey) -> None:
    """Recurrence detection is the whole point of comparing one Friday to the next."""
    assert key.identify(QUERY) == key.identify(QUERY)


def test_normalisation_makes_cosmetic_differences_one_handle(key: QueryIdKey) -> None:
    """`Knee  Replacement` and `knee replacement` are the same recurrence, not two."""
    assert normalise_query("Knee  Replacement") == normalise_query("knee replacement")
    assert key.identify("Knee  Replacement") == key.identify("knee replacement")


def test_a_different_key_gives_a_different_id(tmp_path: Path) -> None:
    """The property that defeats dictionary confirmation."""
    one, _ = load_or_create(tmp_path / "a.key")
    two, _ = load_or_create(tmp_path / "b.key")
    assert one.identify(QUERY) != two.identify(QUERY)


def test_a_handle_cannot_be_reproduced_without_the_secret(key: QueryIdKey) -> None:
    """Somebody holding findings.json cannot test whether a phrase produced a handle.

    The unkeyed digest is exactly what an attacker can compute. It must not match.
    """
    guessed = ID_PREFIX + hashlib.sha256(QUERY.encode("utf-8")).hexdigest()[:12]
    assert key.identify(QUERY) != guessed


def test_different_queries_still_get_different_handles(key: QueryIdKey) -> None:
    assert key.identify(QUERY) != key.identify("orthopedic doctor jaipur")


def test_the_fingerprint_identifies_the_key_without_disclosing_it(key: QueryIdKey) -> None:
    """A manifest reader needs to know whether two runs are comparable, nothing more."""
    assert key.fingerprint
    assert key.fingerprint not in key.identify(QUERY)
    # and it is not the secret, nor enough to compute a handle
    raw = key.path.read_text(encoding="ascii").strip()
    assert key.fingerprint not in raw
    assert raw not in key.fingerprint


def test_two_keys_have_different_fingerprints(tmp_path: Path) -> None:
    one, _ = load_or_create(tmp_path / "a.key")
    two, _ = load_or_create(tmp_path / "b.key")
    assert one.fingerprint != two.fingerprint


def test_rendering_a_key_never_shows_the_secret(key: QueryIdKey) -> None:
    """This object reaches tracebacks like everything else."""
    raw = key.path.read_text(encoding="ascii").strip()
    for rendering in (repr(key), str(key), f"{key}"):
        assert raw not in rendering
    assert key.fingerprint in repr(key)


def test_a_truncated_key_file_is_refused_rather_than_used(tmp_path: Path) -> None:
    """Silently accepting a short key would silently weaken every handle."""
    path = tmp_path / "query_id.key"
    path.write_text("abcd", encoding="ascii")
    with pytest.raises(QueryKeyError) as caught:
        load_or_create(path)
    assert "usable key" in str(caught.value)


def test_the_environment_override_is_honoured(tmp_path: Path) -> None:
    """CI and tests need a key without a file; the operator's machine uses the file."""
    secret = "ab" * KEY_BYTES
    os.environ["APEX_QUERY_ID_KEY"] = secret
    try:
        key, created = resolve(tmp_path)
        assert created is False
        assert not (tmp_path / ".apex_secrets").exists()
        expected, _ = load_or_create(tmp_path / "written.key")
        assert key.identify(QUERY) != expected.identify(QUERY)
    finally:
        del os.environ["APEX_QUERY_ID_KEY"]


def test_the_first_run_notice_names_the_file_to_back_up(key: QueryIdKey) -> None:
    notice = key_notice(key)
    assert str(key.path) in notice
    assert "back it up" in notice.casefold()
    assert key.path.read_text(encoding="ascii").strip() not in notice


def test_a_search_term_uses_the_key_when_given_one(key: QueryIdKey) -> None:
    keyed = SearchTerm(QUERY, source_file="terms.csv", row=1, key=key)
    unkeyed = SearchTerm(QUERY, source_file="terms.csv", row=1)
    assert keyed.query_id == key.identify(QUERY)
    assert keyed.query_id != unkeyed.query_id
    assert keyed.keyed is True
    assert unkeyed.keyed is False


def test_a_keyed_term_still_leaks_nothing(key: QueryIdKey) -> None:
    """Keying must not reopen any of the containment holes."""
    held = SearchTerm(QUERY, source_file="terms.csv", row=1, key=key)
    for rendering in (str(held), repr(held), f"{held}", json.dumps({"t": held}, default=str)):
        assert QUERY not in rendering
    with pytest.raises(AttributeError):
        held.__dict__  # noqa: B018 - reading it is the attack


def test_the_secret_is_not_in_the_repository(repo_root: Path) -> None:
    """A key in git is not a key. The ignore rule is the guardrail."""
    ignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert ".apex_secrets/" in ignore
