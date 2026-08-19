"""Raw search queries, held so they cannot leak (spec §16.1, Phase-6 prerequisite).

A search term is the most sensitive text this system will ever touch. People type
symptoms, diagnoses, doctors' names and their own phone numbers into Google, and the
Watchdog reads all of it. `redact()` masks phone- and email-shaped substrings — real
protection, but shape-based: `paralysis treatment cost dr sharma` contains no digits and
no `@`, so redaction leaves it exactly as written.

So containment here is **structural rather than careful**. The text lives in a private
field. `str()`, `repr()`, f-strings, `%`-formatting, `json.dumps` of a `__dict__`,
`logging` and traceback rendering all reach the same dead end: an opaque `query_id`,
which is a hash. Getting the words back requires calling `.reveal()`, by name, in code —
and a guardrail test asserts that call appears only in the modules allowed to write
git-ignored analysis CSVs.

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
from dataclasses import dataclass, field

QUERY_ID_CHARS = 12
"""Enough to distinguish queries in a report; never enough to reverse one."""

REVEAL_ALLOWED = frozenset(
    {
        "apex_ads/watchdog/analysis_csv.py",
        "apex_ads/util/searchterm.py",
    }
)
"""The only modules that may call `.reveal()`.

Both write to git-ignored `output/` where the operator needs the original query to judge
it. Everything else — reports, logs, dashboards, findings, exceptions — uses `query_id`.
The guardrail test reads this set, so adding a module here is a visible decision in a
diff rather than a quiet import.
"""


ID_PREFIX = "q"
"""Kept non-numeric on purpose.

A bare hex digest can come out all digits, and `redact()` — correctly — masks anything
phone-shaped, so `query:922467584280` was rewritten to `query:[phone]` in the log. Two
different queries then rendered identically and the handle stopped being a handle. The
leading letter takes the id out of the phone pattern without loosening the mask.
"""


def query_id(text: str) -> str:
    """A stable, non-reversible handle for one query."""
    return ID_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()[:QUERY_ID_CHARS]


@dataclass(frozen=True)
class SearchTerm:
    """One search query, plus where it came from. The words are not printable."""

    _text: str = field(repr=False)
    source_file: str
    row: int

    @property
    def query_id(self) -> str:
        return query_id(self._text)

    @property
    def length(self) -> int:
        """Character count. Safe: a length is not a query."""
        return len(self._text)

    def reveal(self) -> str:
        """The raw query. Legal only in `REVEAL_ALLOWED` modules — see this module's docstring."""
        return self._text

    def __str__(self) -> str:
        return f"query:{self.query_id}"

    def __repr__(self) -> str:
        return f"SearchTerm(query_id={self.query_id!r}, file={self.source_file!r}, row={self.row})"

    def __format__(self, spec: str) -> str:
        """f-strings and `format()` land here. There is no format spec that reveals text."""
        return format(str(self), spec)


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
