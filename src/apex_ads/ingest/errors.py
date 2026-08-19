"""Structural failures in the workbook.

These are raised, not collected: if a required section or column is missing, there is no
bundle to hand to the validators, and pretending otherwise produces a cascade of
misleading downstream errors. Every one carries a `Finding` so the caller can report it
in the same shape as every other problem.

Rule IDs are `ING-*` — structural, distinct from the business rules in spec §9.
"""

from __future__ import annotations

from apex_ads.models.findings import Finding, Severity


class WorkbookError(Exception):
    """Base: something about the workbook's structure makes parsing impossible."""

    rule_id = "ING-000"

    def __init__(self, message: str, finding: Finding) -> None:
        super().__init__(message)
        self.finding = finding


def _blocker(
    rule_id: str,
    message: str,
    *,
    sheet: str,
    section: str | None = None,
    row: int | None = None,
    column: str | None = None,
    remedy: str = "",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=Severity.BLOCKER,
        message=message,
        sheet=sheet,
        section=section,
        row=row,
        column=column,
        remedy=remedy,
    )


class MissingSheetError(WorkbookError):
    """A sheet named in `workbook_schema.yaml` is not in the workbook."""

    rule_id = "ING-001"

    def __init__(self, sheet: str, available: list[str]) -> None:
        message = f"sheet {sheet!r} not found; workbook contains {available}"
        super().__init__(
            message,
            _blocker(
                self.rule_id,
                message,
                sheet=sheet,
                remedy="Restore the sheet, or correct sheets: in config/workbook_schema.yaml.",
            ),
        )


class MissingSectionError(WorkbookError):
    """A required section banner (or anchor header row) could not be found."""

    rule_id = "ING-002"

    def __init__(self, sheet: str, section: str, banner: str | None) -> None:
        looked_for = f"banner {banner!r}" if banner else "its header row"
        message = f"section {section!r} not found on {sheet!r} — looked for {looked_for}"
        super().__init__(
            message,
            _blocker(
                self.rule_id,
                message,
                sheet=sheet,
                section=section,
                remedy="Restore the section heading, or update config/workbook_schema.yaml.",
            ),
        )


class MissingColumnError(WorkbookError):
    """A required column is absent from a section's header row."""

    rule_id = "ING-003"

    def __init__(self, sheet: str, section: str, column: str, present: list[str]) -> None:
        message = (
            f"required column {column!r} missing from section {section!r} on {sheet!r}; "
            f"header row has {present}"
        )
        super().__init__(
            message,
            _blocker(
                self.rule_id,
                message,
                sheet=sheet,
                section=section,
                column=column,
                remedy="Restore the column heading exactly, or update "
                "required_columns in workbook_schema.yaml.",
            ),
        )


class CellCoercionError(WorkbookError):
    """A cell could not be read as its declared type. Never a silent NaN."""

    rule_id = "ING-004"

    def __init__(
        self, sheet: str, section: str, row: int, column: str, value: object, target: str
    ) -> None:
        message = f"cannot read {value!r} as {target} in column {column!r}"
        super().__init__(
            message,
            _blocker(
                self.rule_id,
                message,
                sheet=sheet,
                section=section,
                row=row,
                column=column,
                remedy=f"Correct the cell so it reads as {target}.",
            ),
        )


class UnparsableScopeError(WorkbookError):
    """A `Scope` cell matches none of the declared scope patterns."""

    rule_id = "ING-005"

    def __init__(self, sheet: str, section: str, row: int, value: str) -> None:
        message = f"cannot read scope {value!r}"
        super().__init__(
            message,
            _blocker(
                self.rule_id,
                message,
                sheet=sheet,
                section=section,
                row=row,
                column="Scope",
                remedy="Use Account, Ad group, 'Campaign: <name>' or 'Shared list → <campaigns>'.",
            ),
        )


class UnknownRegistryTypeError(WorkbookError):
    """A registry row's `Type` is neither Keyword nor Negative."""

    rule_id = "ING-006"

    def __init__(self, sheet: str, section: str, row: int, value: str, allowed: list[str]) -> None:
        message = f"unknown registry Type {value!r}; expected one of {allowed}"
        super().__init__(
            message,
            _blocker(
                self.rule_id,
                message,
                sheet=sheet,
                section=section,
                row=row,
                column="Type",
                remedy="Set Type to Keyword or Negative.",
            ),
        )


class DuplicateColumnError(WorkbookError):
    """One header row carries the same normalised column name twice.

    Structural, and raised before a single row is read. The header index used to keep the
    first occurrence and drop the rest, so a second `Status` column — or a `Monthly
    budget` pasted beside `Monthly Budget`, which normalises to the same key — was read
    from one position and silently ignored in the other. Whichever column a human had
    been maintaining, they had a 50% chance of the build reading the other one, with
    nothing reported either way.

    Naming both positions matters: "duplicate column Status" sends somebody hunting
    through a wide sheet. "columns 11 and 17" does not.
    """

    rule_id = "ING-007"

    def __init__(
        self, sheet: str, section: str, row: int, duplicates: dict[str, list[str]]
    ) -> None:
        detail = "; ".join(
            f"{name!r} at {', '.join(positions)}" for name, positions in sorted(duplicates.items())
        )
        message = f"section {section!r} on {sheet!r} has repeated column heading(s): {detail}"
        super().__init__(
            message,
            _blocker(
                self.rule_id,
                message,
                sheet=sheet,
                section=section,
                row=row,
                remedy="Delete or rename the duplicate heading so each column name appears "
                "once. Headings that differ only by case or spacing count as the same "
                "column, because that is how the parser matches them.",
            ),
        )
