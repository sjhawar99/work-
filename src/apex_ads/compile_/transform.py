"""Turning validated workbook records into the rows an export will write (spec §10.2).

Three properties matter here and each has a test:

* **Every campaign and ad group is `Paused`.** Applied here, and asserted again in the
  writer. Two independent gates, deliberately (guardrail §18.15).
* **Negative scope is preserved.** Four buckets — account, shared list, campaign, ad
  group — never one flat list, and a shared list's terms are never expanded across its
  campaigns (Decision A4).
* **Output is deterministic.** Everything is sorted, so two runs over one workbook
  produce byte-identical files.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import (
    AdGroupBuild,
    CampaignSettings,
    Keyword,
    Negative,
    WorkbookBundle,
)
from apex_ads.validate.collisions import ScopeResolver

PAUSED = "Paused"

Row = TypeVar("Row")
"""`TypeVar` rather than PEP 695 `def f[T]`, which needs Python 3.12; we support 3.10."""


@dataclass(frozen=True)
class SharedListRow:
    """One term in a shared negative list, with the campaigns that list serves."""

    list_name: str
    text: str
    match_type: str
    applies_to: tuple[str, ...]


@dataclass
class CompiledAccount:
    """Everything an export needs, already ordered and status-forced."""

    campaigns: list[CampaignSettings] = field(default_factory=list)
    ad_groups: list[AdGroupBuild] = field(default_factory=list)
    keywords: list[Keyword] = field(default_factory=list)
    account_negatives: list[Negative] = field(default_factory=list)
    shared_list_rows: list[SharedListRow] = field(default_factory=list)
    campaign_negatives: list[Negative] = field(default_factory=list)
    adgroup_negatives: list[Negative] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "campaigns": len(self.campaigns),
            "ad_groups": len(self.ad_groups),
            "keywords": len(self.keywords),
            "account_negatives": len(self.account_negatives),
            "shared_list_rows": len(self.shared_list_rows),
            "campaign_negatives": len(self.campaign_negatives),
            "adgroup_negatives": len(self.adgroup_negatives),
        }


def _dedupe(
    rows: list[Row],
    key: Callable[[Row], object],
    section: str,
    findings: list[Finding],
) -> list[Row]:
    seen: set[object] = set()
    kept: list[Row] = []
    for row in rows:
        identity = key(row)
        if identity in seen:
            findings.append(
                Finding(
                    rule_id="CMP-100",
                    severity=Severity.INFO,
                    message=f"dropped a duplicate row: {identity}",
                    sheet=getattr(row, "sheet", "—"),
                    row=getattr(row, "row", None),
                    section=section,
                )
            )
            continue
        seen.add(identity)
        kept.append(row)
    return kept


def transform(bundle: WorkbookBundle, rules: Rules) -> CompiledAccount:
    """Compile the bundle into export-ready rows."""
    findings: list[Finding] = []
    resolver = ScopeResolver.from_rules(rules)

    campaigns = sorted(
        (campaign.model_copy(update={"status": PAUSED}) for campaign in bundle.campaigns),
        key=lambda campaign: campaign.name,
    )
    ad_groups = sorted(
        (group.model_copy(update={"status": PAUSED}) for group in bundle.ad_groups),
        key=lambda group: (group.campaign, group.name),
    )
    keywords = sorted(
        _dedupe(
            list(bundle.keywords),
            lambda k: (k.campaign, k.ad_group, k.text, k.match_type),
            "keywords",
            findings,
        ),
        key=lambda k: (k.campaign or "", k.ad_group or "", k.text, k.match_type),
    )

    by_level: dict[str, list[Negative]] = defaultdict(list)
    for negative in bundle.negatives:
        by_level[negative.scope.level].append(negative)

    def resolved(negative: Negative) -> Negative:
        """Make the negative's target explicit for export.

        The workbook keeps a campaign- or ad-group-scoped target inside the `Scope`
        sentence ("Campaign: MLN | Search | Generic | Jaipur") and leaves the Campaign
        column as an em dash. Export needs it in a column, so the scope is materialised
        here — in the transform, where turning human phrasing into machine fields belongs.
        The raw scope is untouched.
        """
        return negative.model_copy(
            update={
                "campaign": negative.campaign or negative.scope.campaign,
                "ad_group": negative.ad_group or negative.scope.ad_group,
            }
        )

    def ordered(level: str) -> list[Negative]:
        return sorted(
            (
                resolved(negative)
                for negative in _dedupe(
                    by_level[level],
                    lambda n: (n.scope.raw, n.list_name, n.text, n.match_type),
                    "negatives",
                    findings,
                )
            ),
            key=lambda n: (n.campaign or "", n.ad_group or "", n.text, n.match_type),
        )

    shared_rows: list[SharedListRow] = []
    for negative in ordered("SHARED_LIST"):
        # The list's terms stay in the list. They are never copied into each campaign.
        shared_rows.append(
            SharedListRow(
                list_name=negative.list_name or "",
                text=negative.text,
                match_type=negative.match_type,
                applies_to=tuple(sorted(resolver.expand(negative.scope.applied_campaigns))),
            )
        )

    return CompiledAccount(
        campaigns=campaigns,
        ad_groups=ad_groups,
        keywords=keywords,
        account_negatives=ordered("ACCOUNT"),
        shared_list_rows=sorted(
            shared_rows, key=lambda row: (row.list_name, row.text, row.match_type)
        ),
        campaign_negatives=ordered("CAMPAIGN"),
        adgroup_negatives=ordered("AD_GROUP"),
        findings=findings,
    )
