"""The validator contract.

A validator reads a `WorkbookBundle` and yields `Finding`s. It never mutates the bundle,
never stops at the first problem, and never talks to the network in Phase 2.

The runner executes **every** validator and collects **every** finding. A human fixing a
workbook wants the whole list, not a game of whack-a-mole.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import WorkbookBundle


@runtime_checkable
class Validator(Protocol):
    """One rule. Independently testable, and identified by a rule ID that never changes."""

    rule_id: str
    severity: Severity

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]: ...


class Rule:
    """Convenience base: carries the rule ID and builds findings with it attached."""

    rule_id: str = "RULE-000"
    severity: Severity = Severity.BLOCKER

    ready_only: bool = False
    """True for rules that only bite when a *deployable* build is being produced.

    `apex validate` is a workbook health check and downgrades these to WARNING, so
    development continues while the call number is still `[REQUIRED BEFORE LAUNCH]`.
    `apex build` (Phase 5) runs them at full severity, so a READY build stays impossible
    until they are satisfied. The rule is written once; only the mode changes.
    """

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        raise NotImplementedError

    def finding(
        self,
        message: str,
        *,
        sheet: str,
        severity: Severity | None = None,
        row: int | None = None,
        section: str | None = None,
        column: str | None = None,
        entity: str | None = None,
        remedy: str = "",
    ) -> Finding:
        return Finding(
            rule_id=self.rule_id,
            severity=severity or self.severity,
            message=message,
            sheet=sheet,
            row=row,
            section=section,
            column=column,
            entity=entity,
            remedy=remedy,
        )
