"""The analysis CSVs (spec §13.6).

**This is the only module in the codebase permitted to call `SearchTerm.reveal()`**, and
it is listed by name in `apex_ads.util.searchterm.REVEAL_ALLOWED`. A guardrail test fails
if any other module reaches the raw query, and adding a module to that set is a visible
line in a diff.

The exemption is narrow and has a reason. `search_term_analysis.csv` is written into
git-ignored `output/`, and the operator genuinely needs the words: "query q9f86d08 took
34% of Ortho spend" is unactionable, because you cannot decide whether a query is junk
without reading it. Everything a person might *forward* — the actions report, the
dashboard, findings, logs — uses the handle instead.

So the split is: **exactly one file, in an ignored directory, that a human opens to make
the decision.** Not the report they paste into a chat message.

Exactly one is load-bearing, and it was briefly two. `routing_issues.csv` also carried a
`search_term` column, and the privacy test codified the contradiction in a constant naming
both files — one line under its own docstring saying every other output must not contain
the words. Two files is not "slightly less private"; it is a different contract from the
one the operator was given, and it doubles the surface somebody can forward by accident.
Routing issues now carry the query ID, which joins to this file.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from apex_ads.util.searchterm import SearchTerm
from apex_ads.watchdog.findings import Analysed
from apex_ads.watchdog.ingest import ParseError
from apex_ads.watchdog.labels import safe_label
from apex_ads.watchdog.observations import Observation

ANALYSIS = "search_term_analysis.csv"
OBSERVATIONS = "negative_observations.csv"
ROUTING = "routing_issues.csv"
PARSE_ERRORS = "parse_errors.csv"

ANALYSIS_HEADERS = [
    "query_id",
    "search_term",
    "classification",
    "matched_on",
    "expected_owner",
    "actual_owner",
    "triggering_keyword",
    "coverage",
    "covered",
    "has_own_keyword",
    "findings",
    "verdicts",
    "impressions",
    "clicks",
    "cost",
    "conversions",
    "source_row",
]

ROUTING_HEADERS = [
    "query_id",
    "classification",
    "expected_owner",
    "actual_owner",
    "coverage",
    "inferred",
    "why",
    "impressions",
    "clicks",
    "cost",
    "conversions",
]
"""No `search_term`, and no `triggering_keyword` either.

The query ID joins to `search_term_analysis.csv`, which is the one artifact permitted to
hold the words. The keyword is omitted for a less obvious reason: for every exact-match
keyword the keyword text *is* the search term, so a column of keywords is a column of
queries wearing a different heading."""

OBSERVATION_HEADERS = [
    "observation",
    "negative",
    "match_type",
    "list",
    "level",
    "approved_reach",
    "served_in",
    "query_ids",
    "impressions",
    "clicks",
    "cost",
    "conversions",
    "what_to_do",
]
"""Observations, not suggestions. No `status`, no proposed scope, nothing paste-ready.

`list` and `approved_reach` are load-bearing: without them a competitor negative and a junk
negative are indistinguishable once written out, which is how an approved
`ROUTE_COMPETITORS` entry once came back next Friday relabelled as junk vocabulary."""

PARSE_ERROR_HEADERS = ["source_file", "row", "query_id", "category", "code", "campaign"]


def _write(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_analysis(directory: Path, analysed: list[Analysed]) -> Path:
    """Every term, with the words. The one place they are written out."""
    rows = []
    for item in analysed:
        rows.append(
            {
                "query_id": item.row.query_id,
                # The single sanctioned reveal in the codebase.
                "search_term": item.row.term.reveal(),
                "classification": item.classification.category.value,
                "matched_on": " ".join(item.classification.matched),
                "expected_owner": str(item.routing.expected) if item.routing.expected else "—",
                "actual_owner": str(item.routing.actual),
                "triggering_keyword": item.routing.coverage.triggering_keyword or "—",
                "coverage": item.routing.coverage.status.value,
                "covered": "yes" if item.routing.coverage.covered else "no",
                "has_own_keyword": "yes" if item.routing.coverage.has_own_keyword else "no",
                "findings": " ".join(finding.type.value for finding in item.findings),
                "verdicts": " ".join(finding.verdict for finding in item.findings),
                "impressions": item.row.impressions,
                "clicks": item.row.clicks,
                "cost": f"{item.row.cost:.2f}",
                "conversions": f"{item.row.conversions:.2f}",
                "source_row": item.row.term.row,
            }
        )
    rows.sort(key=lambda row: (-float(row["cost"]), row["query_id"]))
    return _write(directory / ANALYSIS, ANALYSIS_HEADERS, rows)


def write_routing_issues(directory: Path, analysed: list[Analysed]) -> Path:
    """Leakage only: where the term should have gone, where it went, what it cost."""
    rows = []
    for item in analysed:
        if not item.routing.leaked:
            continue
        rows.append(
            {
                "query_id": item.row.query_id,
                "classification": item.classification.category.value,
                "expected_owner": str(item.routing.expected) if item.routing.expected else "—",
                "actual_owner": str(item.routing.actual),
                # No triggering keyword here: for an exact-match keyword it is the query.
                "coverage": item.routing.coverage.status.value,
                "inferred": "yes" if item.routing.inferred else "no",
                "why": item.routing.reason,
                "impressions": item.row.impressions,
                "clicks": item.row.clicks,
                "cost": f"{item.row.cost:.2f}",
                "conversions": f"{item.row.conversions:.2f}",
            }
        )
    rows.sort(key=lambda row: (-float(row["cost"]), row["query_id"]))
    return _write(directory / ROUTING, ROUTING_HEADERS, rows)


def write_observations(
    directory: Path, observations: list[Observation], terms: list[SearchTerm]
) -> Path:
    """Both observation kinds in one file, so a refusal cannot be read as an omission.

    The negative's own text is withheld when it happens to equal a query in this run —
    `safe_label`. That case is exactly the one where printing account configuration
    discloses a patient's search, and it is why "only one module calls `reveal()`" was true
    without being sufficient.
    """
    return _write(
        directory / OBSERVATIONS,
        OBSERVATION_HEADERS,
        [item.as_record(safe_label(item.negative_text, terms)) for item in observations],
    )


def write_parse_errors(directory: Path, errors: list[ParseError]) -> Path:
    """Always written, empty file included: absence of the file would look like absence
    of the check."""
    return _write(
        directory / PARSE_ERRORS, PARSE_ERROR_HEADERS, [error.as_record() for error in errors]
    )
