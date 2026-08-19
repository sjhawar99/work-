"""Raw search queries, held so they cannot leak (spec §16.1, Phase-6 prerequisite).

A search term is the most sensitive text this system will ever touch. People type
symptoms, diagnoses, doctors' names and their own phone numbers into Google, and the
Watchdog reads all of it. `redact()` masks phone- and email-shaped substrings — real
protection, but shape-based: `paralysis treatment cost dr sharma` contains no digits and
no `@`, so redaction leaves it exactly as written.

### What this does and does not promise

> Raw search text cannot leak through ordinary rendering, logging, serialisation,
> copying, exceptions or generic object inspection without code deliberately crossing the
> protected boundary.

That is the claim, and it is the right threat model: we are protecting against accidental
software and operator leakage, not against hostile Python running inside this process.
Code that deliberately uses introspection can still reach a closure, and saying
"physically impossible to extract" would be the same kind of overclaim this module was
rewritten to remove.

Containment here has to be **structural rather than careful**, and the first attempt
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
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, NoReturn

from apex_ads.util.text import tokenise

if TYPE_CHECKING:
    from apex_ads.util.queryid import QueryIdKey

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


def query_id(text: str, key: QueryIdKey | None = None) -> str:
    """The handle for one query.

    With a `key` — which is how every real run and every Watchdog output works — this is a
    keyed HMAC over the *normalised* query: stable across weeks under one secret, and not
    confirmable by hashing a guessed phrase. See `apex_ads.util.queryid`.

    `key=None` falls back to an unkeyed digest. That path exists so a `SearchTerm` can be
    constructed in a unit test without key plumbing; it is never how the Watchdog runs, and
    `WatchdogRun` requires a real key. The unkeyed form is dictionary-confirmable and is
    marked as such wherever it can reach a file.
    """
    if key is not None:
        return key.identify(text)
    return ID_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()[:QUERY_ID_CHARS]


class SearchTerm:
    """One search query, plus where it came from. The words are not on the object.

    Deliberately not a dataclass and deliberately `__slots__`-only: both of those are what
    made the previous version's `__dict__` readable by anything that serialises objects
    generically.
    """

    __slots__ = ("__open", "keyed", "length", "query_id", "row", "source_file")

    # Declared for the type checker; `__slots__` above is what actually creates them.
    source_file: str
    row: int
    query_id: str
    """The opaque handle. Safe to print, log, put in a report or paste into a message."""
    length: int
    """Character count. Safe: a length is not a query."""
    keyed: bool
    """True when `query_id` came from the run's secret rather than a bare digest.

    Carried on the object so an output can never quietly present an unkeyed, guessable
    handle as though it were a keyed one.
    """

    def __init__(
        self, text: str, *, source_file: str, row: int, key: QueryIdKey | None = None
    ) -> None:
        held = text  # captured by the closure below and never stored as an attribute

        def _open() -> str:
            return held

        # object.__setattr__ because __setattr__ below refuses everything: the instance is
        # immutable once built, so nothing can swap the closure for a different one.
        object.__setattr__(self, "_SearchTerm__open", _open)
        object.__setattr__(self, "source_file", source_file)
        object.__setattr__(self, "row", row)
        object.__setattr__(self, "query_id", query_id(text, key))
        object.__setattr__(self, "length", len(text))
        object.__setattr__(self, "keyed", key is not None)

    # ------------------------------------------------------------------ the boundary
    def reveal(self) -> str:
        """The raw query. Legal only in `REVEAL_ALLOWED` modules — see the module docstring."""
        opener: Callable[[], str] = self._SearchTerm__open  # type: ignore[attr-defined]
        return opener()

    # ------------------------------------------------- answers, rather than the words
    #
    # Classification and coverage both need to *ask questions about* the query without
    # holding it. These return answers: which of the caller's own vocabulary words appeared,
    # and whether a given keyword matches. Neither can be used to recover a word the caller
    # did not already have, which is why `run.py` and the classifier are not on
    # `REVEAL_ALLOWED` and do not need to be.

    def intersect(self, vocabulary: Iterable[str]) -> frozenset[str]:
        """Which of `vocabulary` occur in this query.

        The result is a subset of what the caller passed in — words from the workbook and
        from config, never words the patient contributed. A classifier built on this learns
        "the token `jaipur` appeared" and cannot learn the rest of the sentence.
        """
        return frozenset(set(tokenise(self.reveal())) & set(vocabulary))

    def matched_by(self, keyword_text: str, match_type: str) -> bool:
        """Would this keyword match this query, under Google's semantics? A boolean.

        Uses the compiler's own engine, so "matches" means one thing across the project.
        """
        from apex_ads.validate.collisions import matches  # local: util must not import validate

        return matches(keyword_text, match_type, self.reveal())

    def token_count(self) -> int:
        """How many tokens the query has. A count is not a query."""
        return len(tokenise(self.reveal()))

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
