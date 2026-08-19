"""Raw search queries, held so they cannot leak (spec §16.1, Phase-6 prerequisite).

A search term is the most sensitive text this system will ever touch. People type
symptoms, diagnoses, doctors' names and their own phone numbers into Google, and the
Watchdog reads all of it. `redact()` masks phone- and email-shaped substrings — real
protection, but shape-based: `paralysis treatment cost dr sharma` contains no digits and
no `@`, so redaction leaves it exactly as written.

So containment here has to be **structural rather than careful**, and the first attempt
was not. It stored the query in a private field of an ordinary frozen dataclass and its
docstring claimed that `json.dumps` of a `__dict__` could not expose it. That was simply
false — `vars(term)`, `term.__dict__`, `dataclasses.asdict(term)` and `term._text` all
handed back the patient's search, and the tests only ever attacked `str`, `repr`,
formatting and logging. A claim of structural safety that a one-line `vars()` defeats is
worse than no claim, because everything built on top of it is written as though the
guarantee holds.

The query is now stored **nowhere on the object**. It lives in a closure captured at
construction, reachable only through `reveal()`:

* the class is `__slots__`-only, so there is no `__dict__` and `vars()` raises;
* it is not a dataclass, so `dataclasses.asdict()` does not apply;
* generic `json.dumps(term)` raises `TypeError` rather than rendering fields;
* `__getstate__`/`__reduce__` refuse, so `pickle`, `copy` and `deepcopy` cannot smuggle
  it out through the serialisation protocol;
* `str`, `repr`, f-strings, `%`-formatting, `logging` and traceback rendering all resolve
  to an opaque `query_id`.

Getting the words back means calling `reveal()`, by name, in code. A guardrail test
asserts that neither `reveal()` nor the mangled closure slot appears outside the modules
listed in `REVEAL_ALLOWED`.

`SearchTermError` is the matching exception: it carries the file, the row, the hashed
query ID, a category and an error code, and nothing that could be quoted back. An
exception is the worst possible leak — it prints to a terminal, lands in a log, and gets
pasted into a chat message by whoever hit it.

The point is not that today's code is careful. It is that tomorrow's `log.info(f"bad row:
{term}")` — the natural thing to write, in a hurry, six months from now — prints
`query:q9f86d0818821` instead of a patient's search.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, NoReturn

QUERY_ID_CHARS = 12
"""Enough to distinguish queries in a report; never enough to reverse one."""

REVEAL_ALLOWED = frozenset(
    {
        "apex_ads/watchdog/analysis_csv.py",
        "apex_ads/util/searchterm.py",
    }
)
"""The only modules that may reach the raw query.

`analysis_csv.py` (Phase 6, not written yet) writes to git-ignored `output/`, where the
operator needs the original query to judge it. Everything else — reports, logs,
dashboards, findings, exceptions — uses `query_id`. The guardrail test reads this set, so
adding a module here is a visible decision in a diff rather than a quiet import.
"""

ID_PREFIX = "q"
"""Kept non-numeric on purpose.

A bare hex digest can come out all digits, and `redact()` — correctly — masks anything
phone-shaped, so `query:922467584280` was rewritten to `query:[phone]` in the log. Two
different queries then rendered identically and the handle stopped being a handle. The
leading letter takes the id out of the phone pattern without loosening the mask.
"""


def query_id(text: str) -> str:
    """A stable, non-reversible handle for one query.

    Unkeyed on purpose, and the trade-off is worth stating: a truncated SHA-256 of the
    query is stable across weeks, which is what lets the Watchdog say "this junk term is
    back", and it is also confirmable by dictionary guessing — somebody holding a log can
    test whether a specific phrase produced a given handle. A keyed HMAC would close that
    and would make handles comparable only within one key, so the key would have to
    outlive every report that quotes a handle. Which way that trades is a Phase-6 design
    question about how the Watchdog compares weeks, and it is recorded as an open item
    rather than guessed at here.
    """
    return ID_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()[:QUERY_ID_CHARS]


class SearchTerm:
    """One search query, plus where it came from. The words are not on the object.

    Deliberately not a dataclass and deliberately `__slots__`-only: both of those are what
    made the previous version's `__dict__` readable by anything that serialises objects
    generically.
    """

    __slots__ = ("__open", "length", "query_id", "row", "source_file")

    # Declared for the type checker; `__slots__` above is what actually creates them.
    source_file: str
    row: int
    query_id: str
    """The opaque handle. Safe to print, log, put in a report or paste into a message."""
    length: int
    """Character count. Safe: a length is not a query."""

    def __init__(self, text: str, *, source_file: str, row: int) -> None:
        held = text  # captured by the closure below and never stored as an attribute

        def _open() -> str:
            return held

        # object.__setattr__ because __setattr__ below refuses everything: the instance is
        # immutable once built, so nothing can swap the closure for a different one.
        object.__setattr__(self, "_SearchTerm__open", _open)
        object.__setattr__(self, "source_file", source_file)
        object.__setattr__(self, "row", row)
        object.__setattr__(self, "query_id", query_id(text))
        object.__setattr__(self, "length", len(text))

    # ------------------------------------------------------------------ the boundary
    def reveal(self) -> str:
        """The raw query. Legal only in `REVEAL_ALLOWED` modules — see the module docstring."""
        opener: Callable[[], str] = self._SearchTerm__open  # type: ignore[attr-defined]
        return opener()

    # ------------------------------------------------------------------- immutability
    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError(f"SearchTerm is immutable; cannot set {name!r}")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError(f"SearchTerm is immutable; cannot delete {name!r}")

    # ------------------------------------------------------- generic serialisation off
    def __getstate__(self) -> NoReturn:
        """`pickle`, `copy` and `deepcopy` all come through here. All three are refused.

        Not paranoia: the previous version's slots would have been handed to `pickle` as a
        plain state dict containing the query, which is the same leak as `__dict__` wearing
        a different hat.
        """
        raise TypeError(
            "a SearchTerm cannot be serialised; use query_id, or reveal() inside a module "
            "listed in REVEAL_ALLOWED"
        )

    def __reduce__(self) -> NoReturn:
        raise TypeError(
            "a SearchTerm cannot be pickled; use query_id, or reveal() inside a module "
            "listed in REVEAL_ALLOWED"
        )

    # ------------------------------------------------------------------- safe renderings
    def __str__(self) -> str:
        return f"query:{self.query_id}"

    def __repr__(self) -> str:
        return f"SearchTerm(query_id={self.query_id!r}, file={self.source_file!r}, row={self.row})"

    def __format__(self, spec: str) -> str:
        """f-strings and `format()` land here. There is no format spec that reveals text."""
        return format(str(self), spec)

    # ---------------------------------------------------------------- identity, safely
    def __eq__(self, other: object) -> bool:
        """Compared by handle, never by reading two raw strings back out."""
        if not isinstance(other, SearchTerm):
            return NotImplemented
        return (self.query_id, self.source_file, self.row) == (
            other.query_id,
            other.source_file,
            other.row,
        )

    def __hash__(self) -> int:
        return hash((self.query_id, self.source_file, self.row))


def is_search_term(value: Any) -> bool:
    """Small helper so callers can guard without importing the class into type checks."""
    return isinstance(value, SearchTerm)


class SearchTermError(Exception):
    """A row of search-term data could not be processed.

    Carries the file, the row, the hashed query ID, a category and an error code — never
    the query. An exception message is the leakiest surface there is: it reaches stderr,
    the log file, a traceback, and whatever chat window the operator pastes it into.
    """

    def __init__(
        self,
        *,
        source_file: str,
        row: int,
        query_id: str,
        category: str,
        code: str,
    ) -> None:
        self.source_file = source_file
        self.row = row
        self.query_id = query_id
        self.category = category
        self.code = code
        super().__init__(f"{code}: {category} in {source_file} row {row} (query:{query_id})")

    @classmethod
    def for_term(cls, term: SearchTerm, *, category: str, code: str) -> SearchTermError:
        return cls(
            source_file=term.source_file,
            row=term.row,
            query_id=term.query_id,
            category=category,
            code=code,
        )
