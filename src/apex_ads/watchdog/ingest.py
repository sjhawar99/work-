"""Reading a Google Ads search-terms export (spec §13.1).

This module is the **raw term boundary**. A query exists as plain text for exactly as long
as it takes to hand it to `SearchTerm`; from that line onwards nothing downstream can
print it. Every failure path here — a missing column, an uncoercible number, a short row —
reports the file, the row and the hashed handle, and never the query.

Column names vary by locale and report version, so resolution is alias-driven from
`config/rules.yaml → watchdog.column_aliases`. A missing *required* column is a BLOCKER
and produces no outputs, the same fail-closed discipline as the compiler: a Watchdog that
half-reads an export and reports on what it managed to parse is worse than one that
refuses, because the missing half is invisible.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from apex_ads.models.config import WatchdogRules
from apex_ads.models.findings import Finding, Severity
from apex_ads.util.queryid import QueryIdKey
from apex_ads.util.searchterm import SearchTerm
from apex_ads.util.text import normalise_key, normalise_text

MISSING_COLUMN_RULE = "WD-001"
NO_EXPORT_RULE = "WD-002"
STALE_EXPORT_RULE = "WD-003"
PARSE_ERROR_RULE = "WD-004"
EMPTY_EXPORT_RULE = "WD-005"
UNKEYED_ID_RULE = "WD-006"

REQUIRED_FIELDS = (
    "search_term",
    "campaign",
    "ad_group",
    "keyword",
    "match_type",
    "impressions",
    "clicks",
    "cost",
    "conversions",
)
"""Spec §13.1. Every one of these must resolve, or the run refuses."""

_CURRENCY = str.maketrans({"₹": None, ",": None, "$": None, "%": None})


class ExportError(Exception):
    """The export cannot be read at all. Carries a `Finding` like every other failure."""

    def __init__(self, message: str, finding: Finding) -> None:
        super().__init__(message)
        self.finding = finding


@dataclass(frozen=True)
class SearchTermRow:
    """One export row, with the query already behind the boundary."""

    term: SearchTerm
    campaign: str
    ad_group: str
    keyword: str
    match_type: str
    impressions: int
    clicks: int
    cost: Decimal
    conversions: Decimal

    @property
    def query_id(self) -> str:
        return self.term.query_id


@dataclass(frozen=True)
class ParseError:
    """A row that could not be read. No raw query — the handle, the row and the reason."""

    source_file: str
    row: int
    query_id: str
    category: str
    code: str

    def as_record(self) -> dict[str, str]:
        return {
            "source_file": self.source_file,
            "row": str(self.row),
            "query_id": self.query_id,
            "category": self.category,
            "code": self.code,
        }


@dataclass
class Export:
    """Everything one export yielded, plus what could not be read."""

    path: Path
    rows: list[SearchTermRow] = field(default_factory=list)
    parse_errors: list[ParseError] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    observed_dates: tuple[date | None, date | None] = (None, None)

    @property
    def total_cost(self) -> Decimal:
        return sum((row.cost for row in self.rows), Decimal("0"))


def choose_export(target: Path) -> Path:
    """A file, or the most recently modified CSV in a directory. Never picked silently.

    The caller echoes the returned filename into the report. Reviewing last month's export
    by accident is a quiet way to make a confident bad decision, so which file was read is
    never left implicit.
    """
    if target.is_file():
        return target
    if not target.is_dir():
        raise ExportError(
            f"{target} is neither a file nor a directory",
            _blocker(
                NO_EXPORT_RULE,
                f"no search-terms export found at {target}",
                remedy="Save the Friday export into input/search_terms/, or pass "
                "--search-terms with the file path.",
            ),
        )
    candidates = sorted(
        (path for path in target.iterdir() if path.is_file() and path.suffix.lower() == ".csv"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    if not candidates:
        raise ExportError(
            f"no CSV files in {target}",
            _blocker(
                NO_EXPORT_RULE,
                f"no CSV export in {target}",
                remedy="Export the previous 7 days of search terms from Google Ads and "
                "save the CSV into that folder.",
            ),
        )
    return candidates[0]


def _blocker(rule_id: str, message: str, *, remedy: str, row: int | None = None) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=Severity.BLOCKER,
        message=message,
        sheet="search terms export",
        section="watchdog",
        row=row,
        remedy=remedy,
    )


def resolve_columns(headers: list[str], rules: WatchdogRules) -> dict[str, int]:
    """Alias-driven header resolution, with duplicates refused like the workbook parser.

    Two headers normalising to the same alias would make the reader pick one and ignore the
    other — the `ING-007` bug in a different file format. Refused here for the same reason.
    """
    positions: dict[str, int] = {}
    seen: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = normalise_key(header)
        if not key:
            continue
        if key in seen:
            raise ExportError(
                f"duplicate column {header!r}",
                _blocker(
                    MISSING_COLUMN_RULE,
                    f"the export repeats the column {header!r} at positions "
                    f"{seen[key] + 1} and {index + 1}",
                    remedy="Re-export from Google Ads without duplicated columns.",
                ),
            )
        seen[key] = index

    for field_name, aliases in rules.column_aliases.items():
        for alias in aliases:
            position = seen.get(normalise_key(alias))
            if position is not None:
                positions[field_name] = position
                break

    missing = [name for name in REQUIRED_FIELDS if name not in positions]
    if missing:
        raise ExportError(
            f"missing required columns {missing}",
            _blocker(
                MISSING_COLUMN_RULE,
                f"the export is missing required column(s) {missing}; it has {headers}",
                remedy="Re-export with those columns, or add the export's own heading to "
                "watchdog.column_aliases in config/rules.yaml. The Watchdog refuses "
                "rather than reporting on the part it could read.",
            ),
        )
    return positions


def _number(raw: str) -> Decimal:
    text = normalise_text(raw).translate(_CURRENCY).strip()
    if not text or text in {"-", "--", "—"}:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {raw!r}") from exc


def _date(raw: str) -> date | None:
    text = normalise_text(raw)
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def read_export(
    path: Path, rules: WatchdogRules, key: QueryIdKey, *, today: date | None = None
) -> Export:
    """Read one export. Structural failure raises; per-row failure is collected."""
    export = Export(path=path)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers = _first_header_row(reader, rules)
        positions = resolve_columns(headers, rules)
        date_position = positions.get("day")

        seen_dates: list[date] = []
        # `start=2` so the number matches what a spreadsheet shows: header is row 1.
        for number, raw_row in enumerate(reader, start=2):
            if not any(cell.strip() for cell in raw_row):
                continue
            parsed = _row(raw_row, positions, path, number, key)
            if isinstance(parsed, ParseError):
                export.parse_errors.append(parsed)
                continue
            export.rows.append(parsed)
            if date_position is not None and date_position < len(raw_row):
                found = _date(raw_row[date_position])
                if found is not None:
                    seen_dates.append(found)

    if seen_dates:
        export.observed_dates = (min(seen_dates), max(seen_dates))

    export.findings.extend(_range_findings(export, rules, today=today))
    if export.parse_errors:
        export.findings.append(
            Finding(
                rule_id=PARSE_ERROR_RULE,
                severity=Severity.WARNING,
                message=(
                    f"{len(export.parse_errors)} row(s) of {path.name} could not be read "
                    "and are listed in parse_errors.csv"
                ),
                sheet="search terms export",
                section="watchdog",
                remedy="Open parse_errors.csv, find those rows by number, and re-export "
                "if the count is large. They are counted, never dropped silently.",
            )
        )
    if not export.rows:
        export.findings.append(
            Finding(
                rule_id=EMPTY_EXPORT_RULE,
                severity=Severity.WARNING,
                message=f"{path.name} contains no readable search-term rows",
                sheet="search terms export",
                section="watchdog",
                remedy="Check the export's date range in Google Ads. An empty week is "
                "possible; an empty export usually means the wrong range was selected.",
            )
        )
    return export


def _first_header_row(reader: csv.reader, rules: WatchdogRules) -> list[str]:  # type: ignore[valid-type]
    """Skip the preamble Google Ads puts above the table.

    Real exports begin with a title line and a date line before the header row. Guessing a
    fixed offset would be the row-index mistake the workbook parser exists to avoid, so the
    header row is found by content: the first row that resolves the search-term column.
    """
    wanted = {normalise_key(alias) for alias in rules.column_aliases.get("search_term", [])}
    for row in reader:  # type: ignore[attr-defined]
        keys = {normalise_key(cell) for cell in row}
        if keys & wanted:
            return list(row)
    raise ExportError(
        "no header row found",
        _blocker(
            MISSING_COLUMN_RULE,
            "no header row in the export names a search-term column "
            f"(looked for any of {sorted(wanted)})",
            remedy="Re-export from Google Ads, or add this export's own heading to "
            "watchdog.column_aliases in config/rules.yaml.",
        ),
    )


def _row(
    raw_row: list[str],
    positions: dict[str, int],
    path: Path,
    number: int,
    key: QueryIdKey,
) -> SearchTermRow | ParseError:
    """One row, or a `ParseError` carrying no query text."""
    needed = max(positions.values())
    if len(raw_row) <= needed:
        return ParseError(
            source_file=path.name,
            row=number,
            query_id="unreadable",
            category="short_row",
            code="WD-E001",
        )

    def cell(name: str) -> str:
        return normalise_text(raw_row[positions[name]])

    # The boundary. From here the query cannot be printed by anything downstream.
    term = SearchTerm(cell("search_term"), source_file=path.name, row=number, key=key)

    if not term.length:
        return ParseError(
            source_file=path.name,
            row=number,
            query_id=term.query_id,
            category="empty_search_term",
            code="WD-E002",
        )

    try:
        impressions = _number(raw_row[positions["impressions"]])
        clicks = _number(raw_row[positions["clicks"]])
        cost = _number(raw_row[positions["cost"]])
        conversions = _number(raw_row[positions["conversions"]])
    except ValueError:
        # Deliberately not chaining the original exception: its message quotes the cell,
        # and on a malformed export a cell can hold the query itself.
        return ParseError(
            source_file=path.name,
            row=number,
            query_id=term.query_id,
            category="unreadable_metric",
            code="WD-E003",
        )

    return SearchTermRow(
        term=term,
        campaign=cell("campaign"),
        ad_group=cell("ad_group"),
        keyword=cell("keyword"),
        match_type=cell("match_type").upper(),
        impressions=int(impressions),
        clicks=int(clicks),
        cost=cost,
        conversions=conversions,
    )


def _range_findings(export: Export, rules: WatchdogRules, *, today: date | None) -> list[Finding]:
    """Warn when the export does not look like the previous `lookback_days`."""
    first, last = export.observed_dates
    if first is None or last is None:
        return []

    span = (last - first).days + 1
    reference = today or datetime.now(timezone.utc).date()
    findings: list[Finding] = []

    if span != rules.lookback_days:
        findings.append(
            Finding(
                rule_id=STALE_EXPORT_RULE,
                severity=Severity.WARNING,
                message=(
                    f"the export covers {first} to {last} ({span} day(s)); "
                    f"watchdog.lookback_days is {rules.lookback_days}"
                ),
                sheet="search terms export",
                section="watchdog",
                remedy="Re-export the previous 7 days, or accept the difference "
                "knowingly. The figures below describe the range printed here, not the "
                "range you may have assumed.",
            )
        )

    age = (reference - last).days
    if age > rules.lookback_days:
        findings.append(
            Finding(
                rule_id=STALE_EXPORT_RULE,
                severity=Severity.WARNING,
                message=(
                    f"the export's most recent day is {last}, {age} day(s) before today "
                    f"({reference})"
                ),
                sheet="search terms export",
                section="watchdog",
                remedy="Re-export. Reviewing last month's data by accident is a quiet way "
                "to make a confident bad decision.",
            )
        )
    return findings


def unkeyed_warning(rows: list[SearchTermRow]) -> Finding | None:
    """Refuse to present guessable handles as though they were keyed.

    Cannot happen through the CLI, which always resolves a key. Present so that a future
    caller constructing rows by hand cannot quietly produce a report whose IDs are
    dictionary-confirmable.
    """
    if not rows or all(row.term.keyed for row in rows):
        return None
    return Finding(
        rule_id=UNKEYED_ID_RULE,
        severity=Severity.BLOCKER,
        message="some query IDs in this run were computed without the run key, so they "
        "can be confirmed by guessing a phrase",
        sheet="search terms export",
        section="watchdog",
        remedy="Run through the CLI, which resolves the key from .apex_secrets/ or "
        "$APEX_QUERY_ID_KEY.",
    )
