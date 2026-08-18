"""Tracking and conversion rules (spec §9.7, Decision C4).

Auto-tagging and GCLID survival are load-bearing for Apex measurement. UTM parameters and
tracking templates are **not**, and must never block an otherwise valid campaign — a
build that fails because nobody added an unnecessary tracking template is beautiful
software producing the wrong outcome.

The source of truth is the workbook's `MEASUREMENT CONTRACT` block.
"""

from __future__ import annotations

from collections.abc import Iterable

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import MeasurementContractItem, WorkbookBundle
from apex_ads.validate.base import Rule

SHEET = "02 BUILD"
SECTION = "measurement_contract"


def _item(bundle: WorkbookBundle, needle: str) -> MeasurementContractItem | None:
    for entry in bundle.measurement_contract:
        if needle.casefold() in entry.item.casefold():
            return entry
    return None


class PrimaryConversionDeclared(Rule):
    """`TRK-001` — a primary conversion goal exists and is the one used for bidding."""

    rule_id = "TRK-001"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if not rules.tracking.require_conversion_goal:
            return
        entry = _item(bundle, "primary conversion")
        if entry is None:
            yield self.finding(
                "the measurement contract declares no primary conversion",
                sheet=SHEET,
                section=SECTION,
                remedy="Add a Primary conversion row to MEASUREMENT CONTRACT.",
            )
            return
        if (
            rules.tracking.require_primary_conversion_selected_for_bidding
            and "bidding" not in entry.final_rule.casefold()
        ):
            yield self.finding(
                "the primary conversion is not stated as the goal used for bidding",
                sheet=entry.sheet,
                row=entry.row,
                section=entry.section,
                entity=entry.item,
                remedy="Say which goal bidding optimises to; otherwise Google may "
                "optimise to the wrong thing.",
            )


class CampaignGoalsExist(Rule):
    """`TRK-002` — every campaign names a conversion goal, and it is in the contract."""

    rule_id = "TRK-002"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        declared = bool(_item(bundle, "primary conversion"))
        for campaign in bundle.campaigns:
            if not campaign.primary_conversion:
                yield self.finding(
                    f"{campaign.name} names no primary conversion goal",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                    entity=campaign.name,
                    remedy="Fill Primary conversion / bidding goal.",
                )
            elif not declared:
                yield self.finding(
                    f"{campaign.name} names a conversion goal that the measurement "
                    "contract does not define",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                    entity=campaign.name,
                    remedy="Define it in MEASUREMENT CONTRACT.",
                )


class AutoTaggingOn(Rule):
    """`TRK-003` — auto-tagging is declared on."""

    rule_id = "TRK-003"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if not rules.tracking.require_auto_tagging:
            return
        entry = _item(bundle, "click identity")
        if entry is None or "auto-tagging on" not in entry.final_rule.casefold():
            yield self.finding(
                "auto-tagging is not declared ON in the measurement contract",
                sheet=SHEET,
                section=SECTION,
                remedy="Without auto-tagging there is no GCLID, and no way to tie a lead "
                "back to the click that produced it.",
            )


class GclidPreserved(Rule):
    """`TRK-004` — GCLID survives the journey to the CRM."""

    rule_id = "TRK-004"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if not rules.tracking.preserve_gclid:
            return
        entry = _item(bundle, "click identity")
        if entry is None or "gclid" not in entry.final_rule.casefold():
            yield self.finding(
                "the measurement contract does not require GCLID to be preserved",
                sheet=SHEET,
                section=SECTION,
                remedy="State that GCLID is preserved exactly and survives CRM handoff.",
            )
            return

        for page in bundle.landing_pages:
            if page.tracking and "gclid" not in page.tracking.casefold():
                yield self.finding(
                    f"{page.ad_group}'s landing-page brief does not mention preserving GCLID",
                    sheet=page.sheet,
                    row=page.row,
                    section=page.section,
                    entity=page.ad_group,
                    severity=Severity.WARNING,
                    remedy="Say so in the Tracking column so Web builds it that way.",
                )


class RecommendedUtms(Rule):
    """`TRK-005` — recommended UTM parameters. Recommended, never required."""

    rule_id = "TRK-005"
    severity = Severity.WARNING

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        utm = rules.tracking.utm_params
        if not utm.required:
            yield self.finding(
                f"UTM parameters are recommended, not required "
                f"({', '.join(utm.recommended)}); GCLID is what measurement depends on",
                sheet=SHEET,
                section=SECTION,
                severity=Severity.INFO,
                remedy="None — recorded so nobody mistakes their absence for a defect.",
            )


class TrackingTemplateSyntax(Rule):
    """`TRK-006` — a tracking template, **if present**, is syntactically valid."""

    rule_id = "TRK-006"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        template_rules = rules.tracking.tracking_template
        found = False
        for campaign in bundle.campaigns:
            template = getattr(campaign, "tracking_template", "") or ""
            if not template:
                continue
            found = True
            problems: list[str] = []
            if template.count("{") != template.count("}"):
                problems.append("unbalanced braces")
            if template_rules.require_lpurl_if_present and "{lpurl}" not in template.casefold():
                problems.append("no {lpurl}")
            if " " in template:
                problems.append("contains a space")
            if problems:
                yield self.finding(
                    f"{campaign.name} tracking template is invalid: {', '.join(problems)}",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                    entity=campaign.name,
                    remedy="Correct or remove the template.",
                )
        if not found and not template_rules.required:
            yield self.finding(
                "not applicable: no campaign declares a tracking template, and none is required",
                sheet=SHEET,
                section="campaigns",
                severity=Severity.INFO,
            )


class SensitiveConversionsLocked(Rule):
    """`TRK-007` — Enhanced Conversions stays off for health-related lead data.

    Google's customer-data policy restricts sensitive-category data in Enhanced
    Conversions, and the workbook marks this LOCKED. The rule exists so nobody quietly
    unlocks it.
    """

    rule_id = "TRK-007"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        entry = _item(bundle, "enhanced conversions")
        if entry is None:
            return
        rule_text = entry.final_rule.casefold()
        locked = entry.launch_status.strip().casefold() == "locked"
        forbids = "do not use" in rule_text or "not use" in rule_text
        if locked and not forbids:
            yield self.finding(
                "Enhanced Conversions is marked LOCKED but the rule no longer forbids it",
                sheet=entry.sheet,
                row=entry.row,
                section=entry.section,
                entity=entry.item,
                remedy="Restore the prohibition, or get written compliance approval and record it.",
            )
