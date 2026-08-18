"""Structure rules (spec §9.3) plus the landing-page identity rule.

Everything here works on the canonical `(Campaign, Ad group)` key. Ad-group names are
never assumed globally unique — see `models/identity.py` for why that assumption expires
the moment Apex adds a second hospital.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.identity import AdGroupKey
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.validate.base import Rule

SHEET = "02 BUILD"
FORBIDDEN_STATUSES = {"enabled", "active", "live", "running", "on"}


def ad_group_keys(bundle: WorkbookBundle) -> set[AdGroupKey]:
    return {group.key for group in bundle.ad_groups}


class CampaignCount(Rule):
    """`STR-001` — exactly the expected number of campaigns. Not waivable (Decision A2)."""

    rule_id = "STR-001"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        expected = rules.account.expected_campaign_count
        actual = len(bundle.campaigns)
        if actual != expected:
            yield self.finding(
                f"found {actual} campaigns; Stage 1 is fixed at {expected}",
                sheet=SHEET,
                section="campaigns",
                remedy="Add or remove campaigns, or change expected_campaign_count in "
                "config/rules.yaml — which is a reviewed change, not a waiver.",
            )


class AdGroupCount(Rule):
    """`STR-002` — exactly the expected number of ad groups. Not waivable."""

    rule_id = "STR-002"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        expected = rules.account.expected_ad_group_count
        actual = len(bundle.ad_groups)
        if actual != expected:
            yield self.finding(
                f"found {actual} ad groups; Stage 1 is fixed at {expected}",
                sheet=SHEET,
                section="ad_groups",
                remedy="Add or remove ad groups, or change expected_ad_group_count in "
                "config/rules.yaml.",
            )


class NoOrphans(Rule):
    """`STR-003` — every reference resolves. No ad group, ad or keyword floats free."""

    rule_id = "STR-003"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        campaigns = {campaign.name for campaign in bundle.campaigns}
        keys = ad_group_keys(bundle)

        for group in bundle.ad_groups:
            if group.campaign not in campaigns:
                yield self.finding(
                    f"ad group references campaign {group.campaign!r}, which is not in "
                    "CAMPAIGN SETTINGS",
                    sheet=group.sheet,
                    row=group.row,
                    section=group.section,
                    entity=str(group.key),
                    remedy="Correct the campaign name, or add the campaign.",
                )

        for ad in bundle.ads:
            if ad.key not in keys:
                yield self.finding(
                    f"RSA references {ad.key}, which is not in AD GROUP BUILD",
                    sheet=ad.sheet,
                    row=ad.row,
                    section=ad.section,
                    entity=str(ad.key),
                    remedy="Correct the campaign or ad-group name on the RSA row.",
                )

        for row in [*bundle.keywords, *bundle.negatives]:
            key = row.key
            if key is not None and key not in keys:
                yield self.finding(
                    f"{row.row_type.lower()} {row.text!r} references {key}, which is not "
                    "in AD GROUP BUILD",
                    sheet=row.sheet,
                    row=row.row,
                    section=row.section,
                    entity=str(key),
                    remedy="Correct the campaign or ad-group name on this registry row.",
                )


class CampaignNaming(Rule):
    """`STR-004` — campaign names follow the agreed pattern."""

    rule_id = "STR-004"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        pattern = re.compile(rules.naming.campaign_pattern)
        for campaign in bundle.campaigns:
            if not pattern.match(campaign.name):
                yield self.finding(
                    f"campaign name {campaign.name!r} does not match the agreed pattern",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                    entity=campaign.name,
                    remedy=f"Expected form: {rules.naming.campaign_pattern}",
                )


class NoDuplicateNames(Rule):
    """`STR-005` — no duplicate campaigns, and no duplicate ad groups within a campaign."""

    rule_id = "STR-005"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for name, count in Counter(c.name for c in bundle.campaigns).items():
            if count > 1:
                yield self.finding(
                    f"campaign {name!r} appears {count} times",
                    sheet=SHEET,
                    section="campaigns",
                    entity=name,
                    remedy="Campaign names must be unique.",
                )

        for key, count in Counter(group.key for group in bundle.ad_groups).items():
            if count > 1:
                yield self.finding(
                    f"ad group {key} appears {count} times",
                    sheet=SHEET,
                    section="ad_groups",
                    entity=str(key),
                    remedy="Ad-group names must be unique within their campaign.",
                )


class CampaignNotEnabled(Rule):
    """`STR-006` — nothing in the workbook declares a campaign live.

    The compiler forces `PAUSED` in Phase 5 and asserts it again at export. This is the
    upstream half: a workbook that says a campaign is Enabled disagrees with the whole
    design and should be caught where a human wrote it.
    """

    rule_id = "STR-006"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for campaign in bundle.campaigns:
            if campaign.status.strip().casefold() in FORBIDDEN_STATUSES:
                yield self.finding(
                    f"campaign status is {campaign.status!r}; every compiled campaign is "
                    "created PAUSED and enabled by a human afterwards",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                    entity=campaign.name,
                    remedy="Set the workbook status back to an approval state such as "
                    "APPROVED. Enabling happens in Google Ads, by a person.",
                )


class AdGroupHasKeywords(Rule):
    """`STR-007` — every ad group carries at least the minimum positive keywords."""

    rule_id = "STR-007"
    severity = Severity.WARNING

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        counts: dict[AdGroupKey, int] = defaultdict(int)
        for keyword in bundle.keywords:
            if keyword.key is not None:
                counts[keyword.key] += 1

        minimum = rules.keywords.min_keywords_per_ad_group
        for group in bundle.ad_groups:
            found = counts.get(group.key, 0)
            if found < minimum:
                yield self.finding(
                    f"{group.key} has {found} positive keyword(s); at least {minimum} expected",
                    sheet=group.sheet,
                    row=group.row,
                    section=group.section,
                    entity=str(group.key),
                    remedy="Add keywords in 03 KEYWORDS, or remove the ad group.",
                )


class CampaignAliasesResolve(Rule):
    """`STR-008` — every campaign short name maps to exactly one real campaign.

    The shared-list `Scope` cell names campaigns by short name. Resolution is by the
    explicit alias map in `config/rules.yaml`, never by substring matching, so this rule
    exists to make the map's drift visible: adding a campaign fails here until somebody
    deliberately decides which alias it belongs to.
    """

    rule_id = "STR-008"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        campaigns = {campaign.name for campaign in bundle.campaigns}
        aliases = rules.negatives.campaign_scope_aliases

        for alias, targets in aliases.items():
            for target in targets:
                if target not in campaigns:
                    yield self.finding(
                        f"scope alias {alias!r} points at {target!r}, which is not a "
                        "campaign in this workbook",
                        sheet=SHEET,
                        section="campaigns",
                        entity=alias,
                        remedy="Correct negatives.campaign_scope_aliases in config/rules.yaml.",
                    )

        mapped = {target for targets in aliases.values() for target in targets}
        for name in sorted(campaigns - mapped):
            yield self.finding(
                f"campaign {name!r} has no scope alias, so a shared list could never name it",
                sheet=SHEET,
                section="campaigns",
                entity=name,
                remedy="Add it to negatives.campaign_scope_aliases in config/rules.yaml.",
            )


class LandingPageIdentity(Rule):
    """`STR-LP-001` — every landing-page brief resolves to exactly one `(Campaign, Ad group)`.

    `LANDING PAGE BUILD BRIEFS` has no Campaign column, so the ad-group name is resolved
    through `AD GROUP BUILD`. Zero matches and more than one match are both BLOCKERs:
    ad-group names are unique today by luck, not by design, and this rule is what turns
    that luck into a checked assumption.

    Preferred long-term fix: add a Campaign column to the workbook section. Explicit
    beats a clever join.
    """

    rule_id = "STR-LP-001"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        by_name: dict[str, list[AdGroupKey]] = defaultdict(list)
        for group in bundle.ad_groups:
            by_name[group.name].append(group.key)

        for page in bundle.landing_pages:
            matches = by_name.get(page.ad_group, [])
            if len(matches) == 1:
                continue
            if not matches:
                yield self.finding(
                    f"landing page names ad group {page.ad_group!r}, which is not in "
                    "AD GROUP BUILD",
                    sheet=page.sheet,
                    row=page.row,
                    section=page.section,
                    entity=page.ad_group,
                    remedy="Correct the ad-group name, or add the ad group.",
                )
            else:
                owners = ", ".join(sorted(key.campaign for key in matches))
                yield self.finding(
                    f"ad group name {page.ad_group!r} exists in {len(matches)} campaigns "
                    f"({owners}), so this landing page identifies no single ad group",
                    sheet=page.sheet,
                    row=page.row,
                    section=page.section,
                    entity=page.ad_group,
                    remedy="Add a Campaign column to LANDING PAGE BUILD BRIEFS, or make "
                    "the ad-group names distinct.",
                )


def resolve_landing_pages(bundle: WorkbookBundle) -> dict[AdGroupKey, str]:
    """Canonical landing page per ad group, for rules that need it (Phase 4).

    Only unambiguous matches are returned; ambiguity is `STR-LP-001`'s to report, and a
    silent guess here would defeat it.
    """
    by_name: dict[str, list[AdGroupKey]] = defaultdict(list)
    for group in bundle.ad_groups:
        by_name[group.name].append(group.key)

    resolved: dict[AdGroupKey, str] = {}
    for page in bundle.landing_pages:
        matches = by_name.get(page.ad_group, [])
        if len(matches) == 1:
            resolved[matches[0]] = page.planned_url
    return resolved
