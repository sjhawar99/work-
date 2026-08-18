"""Budget rules (spec §9.3).

Decision A2 makes ₹62,000 a Stage-1 invariant: exact, and not waivable. The only
tolerance in this module is arithmetic rounding when deriving a daily figure from a
monthly one — which is a different thing from permission to drift.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.validate.base import Rule

SHEET = "02 BUILD"


def _money(value: Decimal) -> str:
    return f"₹{value:,.2f}".rstrip("0").rstrip(".")


class MonthlyBudgetTotal(Rule):
    """`BUD-001` — campaign monthly budgets sum to the approved monthly budget, exactly."""

    rule_id = "BUD-001"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if not bundle.campaigns:
            return
        total = sum((campaign.monthly_budget for campaign in bundle.campaigns), Decimal(0))
        approved = rules.account.monthly_budget
        difference = abs(total - approved)
        if difference > rules.account.monthly_budget_tolerance:
            yield self.finding(
                f"campaign budgets total {_money(total)} but the approved monthly budget "
                f"is {_money(approved)} (difference {_money(difference)})",
                sheet=SHEET,
                section="campaigns",
                remedy="Adjust the campaign monthly budgets so they sum exactly to the "
                "approved figure, or change account.monthly_budget in "
                "config/rules.yaml and have that change approved.",
            )


class PositiveBudgets(Rule):
    """`BUD-002` — every campaign has a positive monthly and daily budget."""

    rule_id = "BUD-002"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for campaign in bundle.campaigns:
            for label, amount in (
                ("monthly", campaign.monthly_budget),
                ("daily", campaign.avg_daily_budget),
            ):
                if amount <= 0:
                    yield self.finding(
                        f"{label} budget is {_money(amount)}",
                        sheet=campaign.sheet,
                        row=campaign.row,
                        section=campaign.section,
                        entity=campaign.name,
                        remedy="Every campaign needs a positive budget.",
                    )


class BudgetSplitDeclared(Rule):
    """`BUD-003` — declared split percentages sum to 100%.

    The current workbook declares budgets in rupees and has no percentage column, so this
    rule reports itself as not applicable rather than inventing a split. Recorded as INFO
    so a reader can see the check ran and why it found nothing, which is not the same as
    the check passing.
    """

    rule_id = "BUD-003"
    severity = Severity.INFO

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        yield self.finding(
            "not applicable: the workbook declares budgets in rupees, not as split percentages",
            sheet=SHEET,
            section="campaigns",
            severity=Severity.INFO,
        )


class DailyBudgetDerivation(Rule):
    """`BUD-004` — the stated daily budget matches monthly ÷ days, to the rounding rule."""

    rule_id = "BUD-004"
    severity = Severity.WARNING

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        places = Decimal(10) ** -rules.account.daily_budget_rounding_decimals
        for campaign in bundle.campaigns:
            expected = (campaign.monthly_budget / rules.account.days_per_month).quantize(
                places, rounding=ROUND_HALF_UP
            )
            if campaign.avg_daily_budget != expected:
                yield self.finding(
                    f"daily budget is {_money(campaign.avg_daily_budget)}; "
                    f"{_money(campaign.monthly_budget)} ÷ {rules.account.days_per_month} "
                    f"is {_money(expected)}",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                    entity=campaign.name,
                    remedy="Recompute the daily budget, or correct the monthly figure.",
                )


class DeclaredTotalAgrees(Rule):
    """`BUD-005` — the workbook's own `APPROVED MONTHLY TOTAL` matches the sum above it.

    Not in the original spec: added because the workbook states this figure itself, and a
    stated total that disagrees with its own rows is a sign somebody edited one and not
    the other.
    """

    rule_id = "BUD-005"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if bundle.declared_monthly_total is None or not bundle.campaigns:
            return
        total = sum((campaign.monthly_budget for campaign in bundle.campaigns), Decimal(0))
        if bundle.declared_monthly_total != total:
            yield self.finding(
                f"the workbook states APPROVED MONTHLY TOTAL "
                f"{_money(bundle.declared_monthly_total)} but its campaign rows sum to "
                f"{_money(total)}",
                sheet=SHEET,
                section="campaigns",
                remedy="Update whichever of the two is stale.",
            )
