"""Campaign settings hygiene (spec §9.8).

These are the settings that quietly cost money when wrong: Search Partners and Display
expansion spend budget outside the Search results a Stage-1 plan was written for.
"""

from __future__ import annotations

from collections.abc import Iterable

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import CampaignSettings, WorkbookBundle
from apex_ads.validate.base import Rule

OFF_MARKERS = ("off", "disabled", "no")


def _declares_off(text: str, feature: str) -> bool:
    """True when the networks cell says the feature is off, e.g. `Partners OFF`."""
    folded = text.casefold()
    if feature not in folded:
        return False
    tail = folded.split(feature, 1)[1].lstrip(" :·-")
    return tail.startswith(OFF_MARKERS)


class SearchPartnersOff(Rule):
    """`SET-001` — Search Partners is off unless explicitly approved."""

    rule_id = "SET-001"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if rules.settings.search_partners_allowed:
            return
        for campaign in bundle.campaigns:
            if not _declares_off(campaign.networks, "partners"):
                yield self.finding(
                    f"{campaign.name} does not declare Search Partners OFF "
                    f"(networks: {campaign.networks!r})",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                    entity=campaign.name,
                    remedy="Say 'Partners OFF' in the Networks cell, and set it that way "
                    "in Google Ads.",
                )


class DisplayExpansionOff(Rule):
    """`SET-002` — Display expansion is off for a Search campaign."""

    rule_id = "SET-002"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if rules.settings.display_expansion_allowed:
            return
        for campaign in bundle.campaigns:
            if not _declares_off(campaign.networks, "display"):
                yield self.finding(
                    f"{campaign.name} does not declare Display OFF "
                    f"(networks: {campaign.networks!r})",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                    entity=campaign.name,
                    remedy="Say 'Display OFF' in the Networks cell, and set it that way "
                    "in Google Ads.",
                )


class TargetsDeclared(Rule):
    """`SET-003` — every campaign declares where and in what language it runs."""

    rule_id = "SET-003"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for campaign in bundle.campaigns:
            missing: list[str] = []
            if rules.settings.require_location_targets and not campaign.geo:
                missing.append("location")
            if rules.settings.require_language_targets and not campaign.languages:
                missing.append("language")
            if missing:
                yield self.finding(
                    f"{campaign.name} declares no {' or '.join(missing)} target",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                    entity=campaign.name,
                    remedy="Fill the Geo and Languages columns.",
                )


class LocationOptionDeclared(Rule):
    """`SET-004` — the location option is stated, not left to Google's default.

    "Presence" and "presence or interest" behave very differently for a hospital in
    Jaipur, and the default is not the one this plan assumes.
    """

    rule_id = "SET-004"
    severity = Severity.WARNING

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for campaign in bundle.campaigns:
            if not campaign.location_option:
                yield self.finding(
                    f"{campaign.name} does not state its location option",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                    entity=campaign.name,
                    remedy="State 'Presence — people in or regularly in targeted "
                    "locations' in the Location option column.",
                )


def campaign_by_name(bundle: WorkbookBundle, name: str) -> CampaignSettings | None:
    for campaign in bundle.campaigns:
        if campaign.name == name:
            return campaign
    return None
