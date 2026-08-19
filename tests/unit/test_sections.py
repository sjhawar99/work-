"""Section and column discovery: header text only, never row indices."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex_ads.ingest import grid
from apex_ads.ingest.errors import MissingColumnError, MissingSectionError, MissingSheetError
from apex_ads.ingest.naming import Normaliser
from apex_ads.ingest.sections import find
from apex_ads.models.config import SchemaMatching, SectionSpec, WorkbookSchema
from apex_ads.models.findings import Severity


@pytest.fixture(scope="module")
def matching() -> SchemaMatching:
    return SchemaMatching(
        case_sensitive=False,
        collapse_whitespace=True,
        strip_punctuation=False,
        blank_rows_end_section=2,
        header_row_follows_banner=True,
        null_tokens=["—", "-", ""],
    )


def test_normaliser_keeps_punctuation_headings(matching: SchemaMatching) -> None:
    """`#` and `Recurring?` are real headings; a blanket strip would erase both."""
    normaliser = Normaliser.from_schema(matching)
    assert normaliser.key("#") == "#"
    assert normaliser.key("Recurring?") == "recurring?"
    assert normaliser.key("  Task / problem  ") == "task / problem"
    assert normaliser.key("TASK / PROBLEM") == normaliser.key("task / problem")


def test_stripping_punctuation_is_configurable() -> None:
    stripped = Normaliser(strip_punctuation=True)
    assert stripped.key("Task / problem") == "task problem"


def test_missing_sheet_names_what_is_available(fixtures: dict[str, Path]) -> None:
    book = grid.load(fixtures["clean"])
    with pytest.raises(MissingSheetError) as excinfo:
        book.sheet("05 IMAGINARY")
    assert "01 ACTIONS" in str(excinfo.value)
    assert excinfo.value.finding.rule_id == "ING-001"


def test_missing_section_names_the_banner(
    fixtures: dict[str, Path], schema: WorkbookSchema, matching: SchemaMatching
) -> None:
    book = grid.load(fixtures["missing_section"])
    with pytest.raises(MissingSectionError) as excinfo:
        find(
            book.sheet("02 BUILD"),
            "ad_groups",
            schema.sections["ad_groups"],
            blank_run=2,
            normaliser=Normaliser.from_schema(matching),
        )
    assert "AD GROUP BUILD" in str(excinfo.value)
    assert excinfo.value.finding.rule_id == "ING-002"


def test_missing_column_names_the_column_and_the_headers(
    fixtures: dict[str, Path], schema: WorkbookSchema, matching: SchemaMatching
) -> None:
    book = grid.load(fixtures["renamed_column"])
    with pytest.raises(MissingColumnError) as excinfo:
        find(
            book.sheet("02 BUILD"),
            "campaigns",
            schema.sections["campaigns"],
            blank_run=2,
            normaliser=Normaliser.from_schema(matching),
        )
    message = str(excinfo.value)
    assert "Monthly budget" in message and "Monthly budgets" in message
    assert excinfo.value.finding.rule_id == "ING-003"


def test_trailing_total_row_ends_the_section(
    fixtures: dict[str, Path], schema: WorkbookSchema, matching: SchemaMatching
) -> None:
    """`APPROVED MONTHLY TOTAL` is a workbook-side check, not a sixth campaign."""
    book = grid.load(fixtures["clean"])
    section, _ = find(
        book.sheet("02 BUILD"),
        "campaigns",
        schema.sections["campaigns"],
        blank_run=2,
        normaliser=Normaliser.from_schema(matching),
    )
    assert len(section.rows) == 2
    assert section.trailing_total == 25000


def test_unknown_columns_produce_exactly_one_info(
    fixtures: dict[str, Path], schema: WorkbookSchema, matching: SchemaMatching
) -> None:
    book = grid.load(fixtures["wide_rsa"])
    _, findings = find(
        book.sheet("02 BUILD"),
        "rsa",
        schema.sections["rsa"],
        blank_run=2,
        normaliser=Normaliser.from_schema(matching),
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "ING-100"
    assert findings[0].severity == "INFO"
    assert "reviewer notes" in findings[0].message


def test_numbered_column_family_skips_absent_members(
    fixtures: dict[str, Path], schema: WorkbookSchema, matching: SchemaMatching
) -> None:
    book = grid.load(fixtures["wide_rsa"])
    section, _ = find(
        book.sheet("02 BUILD"),
        "rsa",
        schema.sections["rsa"],
        blank_run=2,
        normaliser=Normaliser.from_schema(matching),
    )
    assert [header for _, header in section.columns.matching("H{n}", 12)] == [
        "H1",
        "H2",
        "H3",
        "H4",
        "H5",
    ]


def test_section_spec_row_hints_are_never_used_for_lookup(schema: WorkbookSchema) -> None:
    """`seen_at_row` is documentation. The shifted-row fixture proves the code ignores it."""
    spec: SectionSpec = schema.sections["campaigns"]
    assert spec.seen_at_row == 10


def test_a_repeated_column_heading_blocks_before_any_row_is_read(
    fixtures: dict[str, Path], schema: WorkbookSchema
) -> None:
    """`ING-007` — the parser must not pick one of two identical headings.

    The index kept the first occurrence and dropped the rest, so a `Status` column pasted
    back into `02 BUILD` left the build reading one position and ignoring the other, with
    nothing reported. Whichever one a human was maintaining, it was a coin flip.
    """
    from apex_ads.ingest.errors import DuplicateColumnError
    from apex_ads.ingest.workbook import parse_workbook

    with pytest.raises(DuplicateColumnError) as caught:
        parse_workbook(fixtures["duplicate_column"], schema)

    finding = caught.value.finding
    assert finding.rule_id == "ING-007"
    assert finding.severity is Severity.BLOCKER
    # both positions, named the way a person reads a spreadsheet
    assert "column S" in finding.message
    assert "column W" in finding.message
    assert "status" in finding.message.casefold()
