"""Withholding account configuration when it happens to equal a search query.

The privacy contract is "**exactly one artifact contains a raw search term**", and until
now that held because of the fixture rather than because of the code. Only one module calls
`reveal()`, which is true and not sufficient: a query can be *identical* to a string the
system prints for entirely legitimate reasons.

Three of those:

* an approved negative — `job` is on `ACCOUNT_JUNK`, and somebody searches `job`;
* a triggering keyword — for every exact-match keyword the keyword text is the query;
* a campaign or list name, in principle.

None of those strings comes from `SearchTerm`. All of them can *be* the query. So the leak
was never through the protected object; it was through equality with account configuration,
and no amount of guarding `reveal()` closes it.

`safe_label()` closes it by construction: any configuration string about to be printed into
a handle-only artifact is withheld when it matches a query in this run. The operator loses
a word and gains a pointer to `search_term_analysis.csv`, which is the one artifact allowed
to hold it — and the loss only happens in the rare case where printing it would have
disclosed the query anyway.

Degrading in exactly the case that matters, and printing normally otherwise, is what makes
the invariant structural instead of lucky.

Note what this module does **not** do: it never reads a query. The comparison runs through
`SearchTerm.has_text()`, which answers yes or no. Adding a third name to `REVEAL_ALLOWED`
to implement a privacy control would have been a poor trade.
"""

from __future__ import annotations

from collections.abc import Iterable

from apex_ads.util.searchterm import SearchTerm

WITHHELD = "[withheld: identical to a search term — see search_term_analysis.csv]"


def safe_label(text: str, terms: Iterable[SearchTerm]) -> str:
    """`text` if printing it discloses nothing, otherwise a withholding note.

    `has_text()` normalises both sides, so `Job` and `job ` are caught too — a literal
    comparison would be the same fixture-dependence in a smaller form.
    """
    if not text:
        return "—"
    return WITHHELD if any(term.has_text(text) for term in terms) else text
