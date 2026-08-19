"""Synthetic search-terms exports, matching the fixture workbook (spec §16.3).

Nothing binary or real is committed. These are written fresh into a tmp directory, and
they mirror the real Google Ads export shape — including the two preamble lines Google
puts above the header row, which is why the reader finds the header by content instead of
counting lines.

The queries here are invented. They exist to exercise each classification branch, and one
of them is deliberately shaped like a real patient search so the privacy tests have
something with no phone or email in it to attack.
"""

from __future__ import annotations

import csv
from pathlib import Path

BRAND = "TST | Search | Brand | Jaipur"
NEURO = "TST | Search | Neuro | Jaipur"

HEADERS = [
    "Day",
    "Search term",
    "Campaign",
    "Ad group",
    "Keyword",
    "Match type",
    "Impr.",
    "Clicks",
    "Cost",
    "Conversions",
]

PREAMBLE = [
    ["Search terms report"],
    ["2026-08-11 - 2026-08-17"],
    [],
]

# (day, term, campaign, ad group, keyword, match, impressions, clicks, cost, conversions)
ROWS: list[list[object]] = [
    # covered brand traffic, correctly routed — no finding
    [
        "2026-08-11",
        "apex hospital jaipur",
        BRAND,
        "Brand | Core",
        "apex hospital",
        "Exact",
        120,
        30,
        "450.00",
        "3",
    ],
    # covered specialty traffic in its own campaign — has its own keyword, so no gap
    [
        "2026-08-11",
        "neurologist in jaipur",
        NEURO,
        "Neuro | Provider",
        "neurologist in jaipur",
        "Phrase",
        200,
        40,
        "980.00",
        "4",
    ],
    # a Neuro term served by the Brand campaign — SPECIALTY_LEAK, and a safe suggestion
    [
        "2026-08-13",
        "neurologist in jaipur appointment",
        BRAND,
        "Brand | Core",
        "apex hospital",
        "Phrase",
        30,
        6,
        "175.00",
        "0",
    ],
    # a brand term served by the Neuro campaign — BRAND_LEAK
    [
        "2026-08-12",
        "apex hospital booking",
        NEURO,
        "Neuro | Provider",
        "neurologist jaipur",
        "Phrase",
        40,
        8,
        "220.50",
        "1",
    ],
    # junk vocabulary already on a negative list — JUNK, reported outright
    [
        "2026-08-12",
        "apex hospital job",
        BRAND,
        "Brand | Core",
        "apex hospital",
        "Phrase",
        60,
        5,
        "95.00",
        "0",
    ],
    # converting, served by a keyword the workbook does not contain — UNAPPROVED_KEYWORD.
    # This is the row the removed HELD_DEMAND used to claim as "demand we are not
    # capturing". It is drift, not a coverage gap: the traffic was served.
    [
        "2026-08-13",
        "paralysis treatment cost jaipur",
        NEURO,
        "Neuro | Provider",
        "neurologist jaipur",
        "Phrase",
        90,
        12,
        "610.75",
        "2",
    ],
    # impressions, no clicks — statistical junk, ranked not declared
    [
        "2026-08-14",
        "free neurology consultation",
        NEURO,
        "Neuro | Provider",
        "neurologist",
        "Phrase",
        300,
        0,
        "0.00",
        "0",
    ],
    # nothing in the taxonomy resolves it — CLASSIFIER_UNRESOLVED
    [
        "2026-08-15",
        "zzz unknown phrase here",
        NEURO,
        "Neuro | Provider",
        "neurologist",
        "Phrase",
        15,
        2,
        "40.00",
        "0",
    ],
    # one query dominating campaign spend — CONCENTRATION ranks it, decides nothing
    [
        "2026-08-16",
        "neurologist jaipur",
        NEURO,
        "Neuro | Provider",
        "neurologist jaipur",
        "Exact",
        500,
        90,
        "3200.00",
        "6",
    ],
]


def _write(path: Path, rows: list[list[object]], headers: list[str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for line in PREAMBLE:
            writer.writerow(line)
        writer.writerow(headers if headers is not None else HEADERS)
        writer.writerows(rows)
    return path


def build_all(directory: Path) -> dict[str, Path]:
    """Every export fixture. Returns `{name: path}`."""
    directory.mkdir(parents=True, exist_ok=True)

    clean = _write(directory / "clean" / "search_terms_week.csv", ROWS)

    missing = _write(
        directory / "missing_column" / "search_terms.csv",
        [row[:8] for row in ROWS],
        headers=HEADERS[:8],
    )

    # A row too short to read, and a row whose cost cell is not a number.
    broken = list(ROWS)
    broken.append(["2026-08-16", "half a row"])
    broken.append(
        [
            "2026-08-16",
            "bad cost row",
            NEURO,
            "Neuro | Provider",
            "neurologist",
            "Phrase",
            10,
            1,
            "not a number",
            "0",
        ]
    )
    malformed = _write(directory / "parse_errors" / "search_terms.csv", broken)

    stale = _write(
        directory / "stale" / "search_terms_old.csv",
        [[f"2025-01-0{n % 9 + 1}", *row[1:]] for n, row in enumerate(ROWS)],
    )

    empty = _write(directory / "empty" / "search_terms.csv", [])

    duplicated = _write(
        directory / "duplicate_column" / "search_terms.csv",
        ROWS,
        headers=[*HEADERS, "Clicks"],
    )

    # PRIVACY ATTACK FIXTURES.
    #
    # The "exactly one raw-query file" invariant held because of this fixture rather than
    # because of the code: no query happened to equal a string the system prints for
    # legitimate reasons. These two make the equality real.
    #
    #   `job` is an approved negative on ACCOUNT_JUNK, and somebody searches exactly `job`
    #   `apex hospital` is an approved EXACT keyword, and somebody searches exactly that
    #
    # Neither string comes from SearchTerm. Both can BE the query.
    equality = _write(
        directory / "equality" / "search_terms.csv",
        [
            [
                "2026-08-11",
                "job",
                BRAND,
                "Brand | Core",
                "apex hospital",
                "Phrase",
                40,
                4,
                "88.00",
                "0",
            ],
            [
                "2026-08-12",
                "apex hospital",
                BRAND,
                "Brand | Core",
                "apex hospital",
                "Exact",
                90,
                20,
                "310.00",
                "2",
            ],
        ],
    )

    # A real export's shape, with no Day column at all: the range can only come from the
    # date line above the table.
    no_day = _write(
        directory / "no_day_column" / "search_terms.csv",
        [row[1:] for row in ROWS],
        headers=HEADERS[1:],
    )

    # Neither a Day column nor a readable date line. The range is unverifiable.
    unverifiable = directory / "unverifiable" / "search_terms.csv"
    unverifiable.parent.mkdir(parents=True, exist_ok=True)
    with unverifiable.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Search terms report"])
        writer.writerow(["all time"])
        writer.writerow([])
        writer.writerow(HEADERS[1:])
        writer.writerows([row[1:] for row in ROWS])

    return {
        "clean": clean,
        "missing_column": missing,
        "parse_errors": malformed,
        "stale": stale,
        "empty": empty,
        "duplicate_column": duplicated,
        "equality": equality,
        "no_day_column": no_day,
        "unverifiable": unverifiable,
    }
