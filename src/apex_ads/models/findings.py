"""Findings: the single currency in which this tool reports problems (spec §7.1).

Phase 1B emits only structural findings — unknown columns, skipped sections. Business
rules arrive with the validator framework in Phase 2, but they share this type.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class Severity(str, Enum):
    """How badly a finding matters. See spec §9.2.

    `str, Enum` rather than `StrEnum`: the package supports Python 3.10, where `StrEnum`
    does not exist. Comparison against a plain string still works.
    """

    BLOCKER = "BLOCKER"
    """Build fails. No deployable files are written."""

    WARNING = "WARNING"
    """Build proceeds. Listed prominently in the report."""

    INFO = "INFO"
    """Recorded in the report appendix."""


class Finding(BaseModel):
    """One problem, in workbook coordinates a human can act on.

    `rule_id` is stable forever: reports, tests and human conversation key off it. Retire
    a rule, never renumber it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    severity: Severity
    message: str
    sheet: str
    row: int | None = None
    section: str | None = None
    column: str | None = None
    entity: str | None = None
    remedy: str = ""

    def __str__(self) -> str:
        where = f"{self.sheet}"
        if self.row is not None:
            where += f" r{self.row}"
        return f"[{self.rule_id}] {where} — {self.message}"
