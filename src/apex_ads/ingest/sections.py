"""Finding sections and their columns by header text — never by row index.

Humans insert rows. Row numbers are a lie waiting to happen (spec §4.3), so every lookup
here works on normalised text: a section is found by its banner, a column by its heading.
`seen_at_row` in the schema is documentation for people, and is never read by this code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apex_ads.ingest.errors import MissingColumnError, MissingSectionError
from apex_ads.ingest.grid import Row, Sheet
from apex_ads.ingest.naming import Normaliser
from apex_ads.models.config import SectionSpec
from apex_ads.models.findings import Finding, Severity
from apex_ads.util.text import is_null_token

UNKNOWN_COLUMN_RULE = "ING-100"
POPULATED_UNKNOWN_RULE = "ING-102"


@dataclass(frozen=True)
class Columns:
    """Resolved column positions for one section, keyed by normalised heading."""

    section: str
    sheet: str
    headers: tuple[str, ...]
    normaliser: Normaliser
    index: dict[str, int] = field(default_factory=dict)

    def position(self, column: str) -> int:
        key = self.normaliser.key(column)
        if key not in self.index:
            raise MissingColumnError(self.sheet, self.section, column, list(self.headers))
        return self.index[key]

    def has(self, column: str) -> bool:
        return self.normaliser.key(column) in self.index

    def matching(self, pattern: str, count: int) -> list[tuple[int, str]]:
        """Positions for a numbered family such as `H{n}`, in ascending order.

        Missing members are skipped rather than assumed: a workbook with only H1 to H5
        yields five entries, not five values and seven blanks.
        """
        found: list[tuple[int, str]] = []
        for number in range(1, count + 1):
            header = pattern.format(n=number)
            if self.has(header):
                found.append((self.position(header), header))
        return found


@dataclass(frozen=True)
class Section:
    """A located section: its header row, its columns and its data rows."""

    name: str
    sheet: str
    spec: SectionSpec
    columns: Columns
    rows: tuple[Row, ...]
    trailing_total: object | None = None


def _is_banner(row: Row, banner: str, match: str, normaliser: Normaliser) -> bool:
    """A banner is a lone heading cell — not a header row with many columns."""
    if row.populated_count > 2:
        return False
    text = normaliser.key(row.text(0))
    wanted = normaliser.key(banner)
    return text.startswith(wanted) if match == "prefix" else text == wanted


def _header_index(headers: tuple[str, ...], normaliser: Normaliser) -> dict[str, int]:
    index: dict[str, int] = {}
    for position, header in enumerate(headers):
        key = normaliser.key(header)
        if key and key not in index:
            index[key] = position
    return index


def _resolve_columns(
    sheet: str, name: str, spec: SectionSpec, row: Row, normaliser: Normaliser
) -> tuple[Columns, list[Finding], list[str]]:
    headers = tuple(row.text(position) for position in range(len(row.cells)))
    columns = Columns(
        section=name,
        sheet=sheet,
        headers=headers,
        normaliser=normaliser,
        index=_header_index(headers, normaliser),
    )

    for column in spec.required_columns:
        columns.position(column)

    known = {normaliser.key(column) for column in spec.required_columns + spec.optional_columns}
    if spec.headline_columns:
        known |= {normaliser.key(spec.headline_columns.format(n=n)) for n in range(1, 31)}
    if spec.description_columns:
        known |= {normaliser.key(spec.description_columns.format(n=n)) for n in range(1, 31)}

    unknown = sorted({key for key in columns.index if key not in known})
    findings: list[Finding] = []
    if unknown:
        findings.append(
            Finding(
                rule_id=UNKNOWN_COLUMN_RULE,
                severity=Severity.INFO,
                message=f"ignoring {len(unknown)} unrecognised column(s): {unknown}",
                sheet=sheet,
                section=name,
                row=row.number,
                remedy="Empty notes columns are expected. A populated one is reported "
                "separately by ING-102.",
            )
        )
    return columns, findings, unknown


def _populated_unknown_columns(
    sheet: str,
    name: str,
    spec: SectionSpec,
    columns: Columns,
    unknown: list[str],
    rows: tuple[Row, ...],
) -> list[Finding]:
    """A column nobody declared, carrying values, in a section that builds the account.

    `EXP-001` catches an unmapped field on a model. It never sees this one: the parser
    used to drop unknown columns with an INFO reading "None needed", before any model
    existed. Add an `Audience exclusion` column to `02 BUILD`, fill it in, and the
    compiler would have produced a build without it and reported nothing.

    Empty notes columns stay an INFO. A populated one blocks until somebody classifies it.
    """
    if spec.allow_unknown_columns or not unknown:
        return []

    findings: list[Finding] = []
    for key in unknown:
        position = columns.index[key]
        # Report the heading as a human typed it, not the normalised lookup key — the
        # point of the message is that somebody can find the column in the sheet.
        heading = columns.headers[position] or key
        populated = [row for row in rows if not is_null_token(row.value(position))]
        if not populated:
            continue
        example = populated[0].text(position)
        findings.append(
            Finding(
                rule_id=POPULATED_UNKNOWN_RULE,
                severity=Severity.BLOCKER,
                message=(
                    f"UNCLASSIFIED SOURCE COLUMN: {heading!r} carries values in "
                    f"{len(populated)} row(s) of {name!r} but nothing reads it "
                    f"(e.g. {example!r})"
                ),
                sheet=sheet,
                section=name,
                column=heading,
                remedy="Add it to required_columns or optional_columns in "
                "workbook_schema.yaml and map it, or set allow_unknown_columns: true for "
                "this section if it is genuinely just notes. A populated column nobody "
                "reads is a setting that silently will not reach Google.",
            )
        )
    return findings


def _find_header_row(
    sheet: Sheet, name: str, spec: SectionSpec, blank_run: int, normaliser: Normaliser
) -> Row:
    """Locate the header row: after the banner if there is one, else by its own columns."""
    required = [normaliser.key(column) for column in spec.required_columns]

    if spec.banner is None:
        for row in sheet.rows:
            keys = {normaliser.key(row.text(position)) for position in range(len(row.cells))}
            if all(column in keys for column in required):
                return row
        raise MissingSectionError(sheet.name, name, None)

    banner_seen = False
    blanks = 0
    for row in sheet.rows:
        if not banner_seen:
            banner_seen = _is_banner(row, spec.banner, spec.banner_match, normaliser)
            continue
        if row.is_blank:
            blanks += 1
            if blanks >= blank_run:
                break
            continue
        blanks = 0
        return row
    raise MissingSectionError(sheet.name, name, spec.banner)


def find(
    sheet: Sheet,
    name: str,
    spec: SectionSpec,
    *,
    blank_run: int,
    normaliser: Normaliser,
    other_banners: tuple[str, ...] = (),
) -> tuple[Section, list[Finding]]:
    """Locate a section and collect its data rows.

    Data collection stops at, in order: the section's declared trailing-total row, any
    other known banner on the sheet, or `blank_run` consecutive blank rows.
    """
    header = _find_header_row(sheet, name, spec, blank_run, normaliser)
    columns, findings, unknown = _resolve_columns(sheet.name, name, spec, header, normaliser)

    required_positions = [columns.position(column) for column in spec.required_columns]
    total_label = normaliser.key(spec.trailing_total_label) if spec.trailing_total_label else None
    banners = tuple(normaliser.key(banner) for banner in other_banners)

    data: list[Row] = []
    trailing_total: object | None = None
    blanks = 0

    for row in sheet.rows:
        if row.number <= header.number:
            continue
        if row.is_blank:
            blanks += 1
            if blanks >= blank_run:
                break
            continue
        blanks = 0

        if total_label is not None:
            labels = {normaliser.key(row.text(position)) for position in range(len(row.cells))}
            if total_label in labels:
                trailing_total = _value_after(row, total_label, normaliser)
                break

        if row.populated_count <= 2 and any(
            normaliser.key(row.text(0)).startswith(banner) for banner in banners if banner
        ):
            break

        if all(is_null_token(row.value(position)) for position in required_positions):
            break

        data.append(row)

    findings.extend(
        _populated_unknown_columns(sheet.name, name, spec, columns, unknown, tuple(data))
    )
    return (
        Section(
            name=name,
            sheet=sheet.name,
            spec=spec,
            columns=columns,
            rows=tuple(data),
            trailing_total=trailing_total,
        ),
        findings,
    )


def _value_after(row: Row, label_key: str, normaliser: Normaliser) -> object | None:
    for position in range(len(row.cells)):
        if normaliser.key(row.text(position)) == label_key:
            for follower in range(position + 1, len(row.cells)):
                if not is_null_token(row.value(follower)):
                    return row.value(follower)
    return None
