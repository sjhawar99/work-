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

So the split is: **one file, in an ignored directory, that a human opens to make the
decision.** Not the report they paste into a chat message.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from apex_ads.watchdog.findings import Analysed
from apex_ads.watchdog.ingest import ParseError
from apex_ads.watchdog.suggestions import Candidate

ANALYSIS = "search_term_analysis.csv"
SUGGESTIONS = "negatives_suggestions.csv"
ROUTING = "routing_issues.csv"
PARSE_ERRORS = "parse_errors.csv"

ANALYSIS_HEADERS = [
    "query_id",
    "search_term",
    "classification",
    "matched_on",
    "expected_owner",
    "actual_owner",
    "covered_by",
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
    "search_term",
    "classification",
    "expected_owner",
    "actual_owner",
    "why",
    "impressions",
    "clicks",
    "cost",
    "conversions",
]

SUGGESTION_HEADERS = [
    "status",
    "negative_text",
    "match_type",
    "level",
    "scope",
    "reason",
    "would_have_blocked",
    "query_ids",
    "impressions",
    "clicks",
    "cost",
    "conversions",
    "conflicts_with",
]

PARSE_ERROR_HEADERS = ["source_file", "row", "query_id", "category", "code"]


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
                "covered_by": " | ".join(
                    f"{keyword.text} ({keyword.match_type.lower()})"
                    for keyword in item.routing.coverage.keywords
                ),
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
                "search_term": item.row.term.reveal(),
                "classification": item.classification.category.value,
                "expected_owner": str(item.routing.expected) if item.routing.expected else "—",
                "actual_owner": str(item.routing.actual),
                "why": item.routing.reason,
                "impressions": item.row.impressions,
                "clicks": item.row.clicks,
                "cost": f"{item.row.cost:.2f}",
                "conversions": f"{item.row.conversions:.2f}",
            }
        )
    rows.sort(key=lambda row: (-float(row["cost"]), row["query_id"]))
    return _write(directory / ROUTING, ROUTING_HEADERS, rows)


def write_suggestions(directory: Path, candidates: list[Candidate]) -> Path:
    """Candidates and conflicts in one file, so a conflict cannot be read as an omission.

    Splitting them would let somebody read `negatives_suggestions.csv`, see nothing about a
    junk term, and conclude the Watchdog missed it — when in fact it deliberately refused.
    """
    return _write(
        directory / SUGGESTIONS,
        SUGGESTION_HEADERS,
        [candidate.as_record() for candidate in candidates],
    )


def write_parse_errors(directory: Path, errors: list[ParseError]) -> Path:
    """Always written, empty file included: absence of the file would look like absence
    of the check."""
    return _write(
        directory / PARSE_ERRORS, PARSE_ERROR_HEADERS, [error.as_record() for error in errors]
    )
