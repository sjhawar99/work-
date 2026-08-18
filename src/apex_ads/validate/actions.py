"""Action-item rules (spec §9.9).

`01 ACTIONS` has two tables with different columns. Both are checked; neither is forced
into the other's shape.

In Stage 1 the waivable-rule list is empty (Decision A2). A waiver records that a human
consciously accepted an open item — it is an audit trail, not an override.
"""

from __future__ import annotations

from collections.abc import Iterable

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import ActionItem, WorkbookBundle
from apex_ads.validate.base import Rule

OPEN_STATUSES = {"open", "in progress", "wip", "blocked"}
CLOSED_STATUSES = {"done", "closed", "complete", "completed"}
WAIVED_STATUS = "waived"


def _is_open(status: str) -> bool:
    return status.strip().casefold() in OPEN_STATUSES


def _severity_of(value: str) -> str:
    return value.strip().casefold()


def all_actions(bundle: WorkbookBundle) -> list[ActionItem]:
    """Both tables, read through the fields they genuinely share."""
    return [*bundle.blocking_actions, *bundle.running_actions]


class NoOpenRedActions(Rule):
    """`ACT-001` — no RED action item is still open, in either table."""

    rule_id = "ACT-001"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for action in all_actions(bundle):
            if _severity_of(action.severity) == "red" and _is_open(action.status):
                yield self.finding(
                    f"RED action still {action.status}: {action.task!r} ({action.owner})",
                    sheet=action.sheet,
                    row=action.row,
                    section=action.section,
                    entity=action.task,
                    remedy="Close the item in 01 ACTIONS, or reduce its severity with the "
                    "owner's agreement.",
                )


class OpenAmberActions(Rule):
    """`ACT-002` — open AMBER items are listed, not blocked."""

    rule_id = "ACT-002"
    severity = Severity.WARNING

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for action in all_actions(bundle):
            if _severity_of(action.severity) == "amber" and _is_open(action.status):
                yield self.finding(
                    f"AMBER action still open: {action.task!r} ({action.owner})",
                    sheet=action.sheet,
                    row=action.row,
                    section=action.section,
                    entity=action.task,
                    remedy="Close it before launch if it affects the build.",
                )


class WaiversAreAccountable(Rule):
    """`ACT-003` — a waived item names an owner and a reason."""

    rule_id = "ACT-003"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for action in all_actions(bundle):
            if action.status.strip().casefold() != WAIVED_STATUS:
                continue
            if not action.owner:
                yield self.finding(
                    f"waived item {action.task!r} names no owner",
                    sheet=action.sheet,
                    row=action.row,
                    section=action.section,
                    entity=action.task,
                    remedy="A waiver needs a named person who accepted it.",
                )
