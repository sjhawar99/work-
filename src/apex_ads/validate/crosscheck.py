"""Cross-checking the workbook's own dashboard panels.

The workbook states figures it has computed itself — approved monthly budget, open RED
blockers, Broad positives, keyword counts. The compiler recomputes every one of them and
reports disagreement rather than trusting the cell.

These are WARNINGs: a stale panel is a signal that somebody edited rows without
refreshing a summary, which is worth knowing and is not by itself a reason to stop.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import Decimal, InvalidOperation

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.validate.actions import _is_open, _severity_of, all_actions
from apex_ads.validate.base import Rule


def _open_red_count(bundle: WorkbookBundle) -> Decimal:
    open_red = [
        action
        for action in all_actions(bundle)
        if _severity_of(action.severity) == "red" and _is_open(action.status)
    ]
    return Decimal(len(open_red))


def _broad_positives(bundle: WorkbookBundle) -> Decimal:
    return Decimal(len([k for k in bundle.keywords if k.match_type == "BROAD"]))


def _monthly_total(bundle: WorkbookBundle) -> Decimal:
    return sum((campaign.monthly_budget for campaign in bundle.campaigns), Decimal(0))


CHECKS: dict[str, tuple[str, Callable[[WorkbookBundle], Decimal]]] = {
    "Approved monthly": ("pre_flight", _monthly_total),
    "Open RED blockers": ("pre_flight", _open_red_count),
    "Broad positives": ("pre_flight", _broad_positives),
    "APPROVED POSITIVES": ("keyword_counts", lambda b: Decimal(len(b.keywords))),
    "APPROVED NEGATIVES": ("keyword_counts", lambda b: Decimal(len(b.negatives))),
}


class PanelsAgreeWithTheRows(Rule):
    """`XCHK-001` — a stated figure matches the figure recomputed from the rows."""

    rule_id = "XCHK-001"
    severity = Severity.WARNING

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for field, (panel_name, compute) in CHECKS.items():
            panel = bundle.panels.get(panel_name)
            if panel is None or field not in panel.values:
                continue
            stated_text = panel.values[field]
            try:
                stated = Decimal(stated_text.replace(",", ""))
            except InvalidOperation:
                continue
            computed = compute(bundle)
            if stated != computed:
                yield self.finding(
                    f"the workbook states {field} = {stated_text}, but the rows give {computed}",
                    sheet=panel.sheet,
                    section=panel_name,
                    entity=field,
                    remedy="Refresh the panel, or find out which side is stale.",
                )
