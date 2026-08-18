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
