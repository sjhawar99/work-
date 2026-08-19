"""Search-query containment (spec §16.1).

These tests are the Phase-6 precondition. The Watchdog does not exist yet; the guarantee
it will depend on has to be in place and enforced *before* the first line of it is
written, because "remember not to log the query" is not a guarantee.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import pickle
import re
from pathlib import Path

import pytest

from apex_ads.util.logging import JsonLinesFormatter, setup_logging
from apex_ads.util.searchterm import REVEAL_ALLOWED, SearchTerm, SearchTermError

# Real-shaped queries with no phone or email in them, so shape-based redaction cannot help.
SENSITIVE = [
    "paralysis treatment cost apex jaipur",
    "dr sharma neurologist appointment mrs gupta",
    "kidney failure last stage how long to live",
    "apex hospital negligence complaint",
]


@pytest.fixture()
def term() -> SearchTerm:
    return SearchTerm(SENSITIVE[0], source_file="search_terms_2026-08.csv", row=42)


@pytest.mark.parametrize("query", SENSITIVE)
def test_no_rendering_of_a_search_term_reveals_it(query: str) -> None:
    """`str`, `repr`, f-strings, `%` and `format()` all have to be dead ends."""
    held = SearchTerm(query, source_file="terms.csv", row=7)
    renderings = [
        str(held),
        repr(held),
        f"{held}",
        f"{held!s}",
        f"{held!r}",
        f"{held:>40}",
        "%s" % (held,),  # noqa: UP031 - the careless form is the point
        format(held),
        "".join(str(part) for part in (held,)),
    ]
    for rendering in renderings:
        assert query not in rendering, rendering
        assert held.query_id in rendering


def test_the_words_come_back_only_by_asking(term: SearchTerm) -> None:
    """Containment must not be lossy — `output/` needs the real query."""
    assert term.reveal() == SENSITIVE[0]
    assert term.length == len(SENSITIVE[0])


def test_query_ids_are_stable_and_distinct() -> None:
    first = SearchTerm(SENSITIVE[0], source_file="a.csv", row=1)
    again = SearchTerm(SENSITIVE[0], source_file="b.csv", row=999)
    other = SearchTerm(SENSITIVE[1], source_file="a.csv", row=1)
    assert first.query_id == again.query_id
    assert first.query_id != other.query_id


@pytest.mark.parametrize("query", SENSITIVE)
def test_an_exception_carries_the_handle_and_not_the_query(query: str) -> None:
    """The leakiest surface: stderr, the log file, a traceback, a pasted chat message."""
    held = SearchTerm(query, source_file="terms.csv", row=11)
    error = SearchTermError.for_term(held, category="unparsable_row", code="WD-E001")

    for rendering in (str(error), repr(error), f"{error}"):
        assert query not in rendering
    assert error.query_id in str(error)
    assert error.code == "WD-E001"
    assert error.category == "unparsable_row"
    assert error.row == 11
    assert error.source_file == "terms.csv"


def test_a_raised_search_term_error_leaks_nothing_through_a_traceback() -> None:
    """Not the message alone — the whole rendered traceback."""
    import traceback

    held = SearchTerm(SENSITIVE[2], source_file="terms.csv", row=3)
    try:
        raise SearchTermError.for_term(held, category="bad_encoding", code="WD-E002")
    except SearchTermError as exc:
        rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert SENSITIVE[2] not in rendered
    assert held.query_id in rendered


@pytest.mark.parametrize("query", SENSITIVE)
def test_logging_a_search_term_writes_the_handle(query: str, tmp_path: Path) -> None:
    """The natural careless line — `log.info(f"skipping {term}")` — must be safe."""
    held = SearchTerm(query, source_file="terms.csv", row=5)
    logger = setup_logging("test-run", log_dir=tmp_path)
    logger.info("skipping %s", held)
    logger.info(f"skipping {held}")
    for handler in logger.handlers:
        handler.flush()

    written = (tmp_path / "test-run.log").read_text(encoding="utf-8")
    assert query not in written
    assert held.query_id in written
    logging.getLogger("apex_ads").handlers.clear()


def test_the_json_formatter_cannot_serialise_a_term_into_a_line() -> None:
    """Even `%r` of the object, which some formatters use, resolves to the handle."""
    held = SearchTerm(SENSITIVE[3], source_file="terms.csv", row=1)
    record = logging.LogRecord(
        name="apex_ads",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="failed on %r",
        args=(held,),
        exc_info=None,
    )
    line = JsonLinesFormatter("run").format(record)
    assert SENSITIVE[3] not in line
    assert held.query_id in json.loads(line)["message"]


# ------------------------------------------------- generic serialisation is a dead end
#
# The first version of this module stored the query in a private field of a frozen
# dataclass and claimed structural safety. `vars(term)`, `term.__dict__`,
# `dataclasses.asdict(term)` and `term._text` all handed the query straight back, and no
# test attacked any of them. These do.


@pytest.mark.parametrize("query", SENSITIVE)
def test_vars_cannot_reach_the_query(query: str) -> None:
    held = SearchTerm(query, source_file="terms.csv", row=1)
    with pytest.raises(TypeError):
        vars(held)


@pytest.mark.parametrize("query", SENSITIVE)
def test_there_is_no_instance_dict_to_read(query: str) -> None:
    held = SearchTerm(query, source_file="terms.csv", row=1)
    with pytest.raises(AttributeError):
        held.__dict__  # noqa: B018 - reading it is the attack


@pytest.mark.parametrize("query", SENSITIVE)
def test_asdict_does_not_apply(query: str) -> None:
    """Not a dataclass, so the dataclass escape hatch is not there to use."""
    held = SearchTerm(query, source_file="terms.csv", row=1)
    assert not dataclasses.is_dataclass(held)
    with pytest.raises(TypeError):
        dataclasses.asdict(held)  # type: ignore[call-overload]


@pytest.mark.parametrize("query", SENSITIVE)
def test_generic_json_serialisation_refuses_rather_than_rendering(query: str) -> None:
    held = SearchTerm(query, source_file="terms.csv", row=1)
    with pytest.raises(TypeError):
        json.dumps(held)
    with pytest.raises(TypeError):
        json.dumps({"term": held})
    # and a default= that stringifies unknown objects still only gets the handle
    rendered = json.dumps({"term": held}, default=str)
    assert query not in rendered
    assert held.query_id in rendered


@pytest.mark.parametrize("query", SENSITIVE)
def test_pickle_and_copy_cannot_smuggle_it_out(query: str) -> None:
    """The serialisation protocol is the same leak as `__dict__` wearing a different hat."""
    held = SearchTerm(query, source_file="terms.csv", row=1)
    for attempt in (
        lambda: pickle.dumps(held),
        lambda: copy.copy(held),
        lambda: copy.deepcopy(held),
    ):
        with pytest.raises(TypeError):
            attempt()


@pytest.mark.parametrize("query", SENSITIVE)
def test_the_old_private_field_no_longer_exists(query: str) -> None:
    """`term._text` was the shortest leak of all. It is gone, not merely discouraged."""
    held = SearchTerm(query, source_file="terms.csv", row=1)
    with pytest.raises(AttributeError):
        held._text  # type: ignore[attr-defined]  # noqa: B018 - reading it is the attack


@pytest.mark.parametrize("query", SENSITIVE)
def test_a_term_is_immutable(query: str) -> None:
    """Nothing may swap the closure for one that returns different text."""
    held = SearchTerm(query, source_file="terms.csv", row=1)
    with pytest.raises(AttributeError):
        held.row = 2  # type: ignore[misc]
    with pytest.raises(AttributeError):
        held.source_file = "elsewhere"  # type: ignore[misc]


def test_no_attribute_on_a_term_holds_the_raw_text() -> None:
    """A sweep, rather than a list: every reachable attribute, checked against the query.

    Written this way so a future field added to `SearchTerm` is covered without anybody
    remembering to extend a list of forbidden names.
    """
    query = SENSITIVE[2]
    held = SearchTerm(query, source_file="terms.csv", row=1)
    for name in dir(held):
        if name in {"reveal", "__init__", "__getstate__", "__reduce__"}:
            continue
        try:
            value = getattr(held, name)
        except (AttributeError, TypeError):
            continue
        assert query not in repr(value), f"{name} exposes the query"


# ------------------------------------------------------------------------- guardrails


def test_the_raw_query_is_reached_only_where_it_is_allowed(repo_root: Path) -> None:
    """Containment holds only while the two ways in stay where they are declared.

    Two ways, not one. `.reveal()` is the documented boundary; `_SearchTerm__open` is the
    mangled closure slot, which is what somebody reaches for when `reveal()` is
    inconvenient. Checking only the first would guard the front door and leave the window.

    A future module that needs the raw query has to add itself to `REVEAL_ALLOWED`, which
    shows up in a diff as a deliberate decision instead of arriving as an import.
    """
    ways_in = re.compile(r"\.reveal\s*\(|_SearchTerm__open")
    offenders = []
    for path in sorted((repo_root / "src").rglob("*.py")):
        relative = path.relative_to(repo_root / "src").as_posix()
        if relative in REVEAL_ALLOWED:
            continue
        if ways_in.search(path.read_text(encoding="utf-8")):
            offenders.append(relative)
    assert not offenders, (
        f"{offenders} reach SearchTerm's raw query without being listed in REVEAL_ALLOWED. "
        "Add the module deliberately, or use query_id."
    )


def test_the_guardrail_would_actually_catch_an_offender(tmp_path: Path) -> None:
    """A guardrail nobody has seen fail is a guardrail nobody knows works.

    Both spellings are checked against a module that is not on the allow-list.
    """
    ways_in = re.compile(r"\.reveal\s*\(|_SearchTerm__open")
    assert ways_in.search("value = term.reveal()")
    assert ways_in.search("value = term._SearchTerm__open()")
    assert not ways_in.search("value = term.query_id")
