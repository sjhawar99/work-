"""Typed records parsed from the four-sheet workbook.

Every record carries `Provenance`, so any finding can be traced to the exact cell that
caused it. Nothing here validates business rules — that is Phase 2. These models describe
*shape*: what the workbook says, typed, with its origin attached.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apex_ads.models.findings import Finding

MatchType = Literal["EXACT", "PHRASE", "BROAD"]
NegativeLevel = Literal["ACCOUNT", "SHARED_LIST", "CAMPAIGN", "AD_GROUP"]
RegistryType = Literal["KEYWORD", "NEGATIVE"]
AssetKind = Literal["HEADLINE", "DESCRIPTION"]


class Record(BaseModel):
    """Base for every parsed record. Unknown fields are a bug, not a shrug."""

    model_config = ConfigDict(extra="forbid")


class Provenance(Record):
    """Where a record came from. `row` is 1-based, matching what Excel shows a human."""

    sheet: str
    row: int
    section: str


# ------------------------------------------------------------------------- 01 ACTIONS
# Two tables with genuinely different columns. Modelled separately rather than forced
# into one fake schema that fits neither.


class BlockingAction(Provenance):
    """`BLOCKING — DO NOT LAUNCH UNTIL THESE CLOSE`."""

    number: int | None
    task: str
    type: str
    owner: str
    due: date | None
    status: str
    severity: str
    done_when: str


class RunningAction(Provenance):
    """`RUNNING ACTIONS — BUILD + FIX IN THE SAME INBOX`."""

    number: int | None
    date_raised: date | None
    task: str
    type: str
    required_action: str
    owner: str
    due: date | None
    status: str
    severity: str
    blocked_by: str
    recurring: str


# --------------------------------------------------------------------------- 02 BUILD


class CampaignSettings(Provenance):
    """`CAMPAIGN SETTINGS — ONE ROW PER CAMPAIGN`."""

    number: int | None
    name: str
    monthly_budget: Decimal
    avg_daily_budget: Decimal
    campaign_type: str
    networks: str
    geo: str
    location_option: str
    languages: str
    launch_bidding: str
    legacy_avg_cpc: Decimal | None
    launch_max_cpc: Decimal | None
    bidding_review_gate: str
    primary_conversion: str
    secondary_conversions: str
    call_phone_number: str
    call_schedule: str
    automation_guardrails: str
    status: str
    why: str
    launch_date: date | None
    owner: str


class AdGroupBuild(Provenance):
    """`AD GROUP BUILD — EXACT NAMES + DESTINATIONS`."""

    number: int | None
    campaign: str
    name: str
    what_it_owns: str
    dominant_intent: str
    planned_landing_page: str
    """A PATH (`/google/apex-jaipur`), preserved as written. Never joined here."""
    call_asset: str
    keyword_source: str
    negative_lists: list[str]
    """Parsed from `ACCOUNT_JUNK · OUTSIDE_GEO`, order preserved."""
    negative_lists_raw: str
    rsa: str
    status: str
    notes: str


class LandingPageBrief(Provenance):
    """`LANDING PAGE BUILD BRIEFS — NINE PAGES, NO INTERPRETATION`."""

    ad_group: str
    planned_url: str
    """A PATH, preserved as written (spec §4.3; joined with `base_url` only at check time)."""
    user_question: str
    hero_must_answer: str
    proof_trust: str
    primary_cta: str
    must_include: str
    tracking: str
    status: str


class SupportingAsset(Provenance):
    """`SUPPORTING ASSETS — BUILD BEFORE LAUNCH`."""

    asset_type: str
    scope: str
    text_header: str
    url_values: str
    description_1: str
    description_2: str
    status: str


class MeasurementContractItem(Provenance):
    """`MEASUREMENT CONTRACT — DO NOT LET GOOGLE OPTIMISE TO THE WRONG THING`."""

    item: str
    final_rule: str
    launch_status: str
    owner: str
    qa_evidence: str
    source_note: str


class AdAsset(Record):
    """One unpivoted RSA asset: `H7` becomes position 7, kind HEADLINE."""

    kind: AssetKind
    position: int
    text: str
    column: str
    """The originating column header (`H7`), kept so a finding can name the cell."""


class ResponsiveSearchAd(Provenance):
    """`RSA 1` — one wide row per ad group, unpivoted into typed assets."""

    campaign: str
    ad_group: str
    headlines: list[AdAsset]
    descriptions: list[AdAsset]

    @property
    def headline_texts(self) -> list[str]:
        return [asset.text for asset in self.headlines]

    @property
    def description_texts(self) -> list[str]:
        return [asset.text for asset in self.descriptions]


# ------------------------------------------------------------------------ 03 KEYWORDS


class Scope(Record):
    """The parsed reading of the workbook's `Scope` cell.

    `raw` is the source of truth and survives round-trip unchanged; everything else is
    this tool's interpretation of it, and is what `NEG-008` will cross-check against the
    approved `applies_to` in `rules.yaml` (Phase 3).
    """

    raw: str
    level: NegativeLevel
    campaign: str | None = None
    ad_group: str | None = None
    applied_campaigns: list[str] = Field(default_factory=list)
    """Short names as written (`Neuro`, `Generic`). Expanded to full names in Phase 3."""


class RegistryRow(Provenance):
    """Fields shared by both rows of the single `03 KEYWORDS` registry."""

    campaign: str | None
    ad_group: str | None
    scope: Scope
    row_type: RegistryType
    match_type: MatchType
    match_type_raw: str
    """As written. `Modified Broad` normalises to PHRASE at parse time (Decision A3);
    the `KW-008` warning that reports it belongs to Phase 3."""
    text: str
    copy_paste_value: str
    """As written in the workbook. DERIVED data, never source truth (KW-009)."""
    copy_paste_expected: str
    """What this tool regenerates from `text` + `match_type`."""
    list_name: str | None
    status: str
    why: str
    added_by: str
    added_on: date | None

    @property
    def copy_paste_matches(self) -> bool:
        return self.copy_paste_value == self.copy_paste_expected


class Keyword(RegistryRow):
    """`Type = Keyword` — something we are paying to show ads for."""

    row_type: Literal["KEYWORD"] = "KEYWORD"


class Negative(RegistryRow):
    """`Type = Negative` — something that stops an ad showing, within its scope."""

    row_type: Literal["NEGATIVE"] = "NEGATIVE"

    @property
    def level(self) -> NegativeLevel:
        return self.scope.level


# ---------------------------------------------------------------------------- 04 DAILY


class DailyLogRow(Provenance):
    """`04 DAILY` — context and provenance only.

    Guardrail: nothing in this table may influence a compilation decision. It is carried
    on the bundle so the Watchdog can read it, and for no other reason.
    """

    date: date | None
    campaign: str
    planned_daily_budget: Decimal | None
    spend: Decimal | None
    clicks: int | None
    raw_leads: str
    breakage_check: str
    changed_today: str
    delivery_signal: str
    qualified_leads: str
    appointments: str
    attended_opd: str


# ---------------------------------------------------------------------------- bundle


class PanelValues(Record):
    """A dashboard panel the workbook states and the compiler independently recomputes."""

    sheet: str
    values: dict[str, str]


class WorkbookBundle(Record):
    """Everything parsed from one workbook, plus how to prove which file it was."""

    source_path: Path
    source_sha256: str
    source_mtime: datetime
    """Local file modification time. Advisory only — see `WB-001`, spec §4.4."""

    blocking_actions: list[BlockingAction] = Field(default_factory=list)
    running_actions: list[RunningAction] = Field(default_factory=list)
    campaigns: list[CampaignSettings] = Field(default_factory=list)
    ad_groups: list[AdGroupBuild] = Field(default_factory=list)
    landing_pages: list[LandingPageBrief] = Field(default_factory=list)
    supporting_assets: list[SupportingAsset] = Field(default_factory=list)
    measurement_contract: list[MeasurementContractItem] = Field(default_factory=list)
    ads: list[ResponsiveSearchAd] = Field(default_factory=list)
    keywords: list[Keyword] = Field(default_factory=list)
    negatives: list[Negative] = Field(default_factory=list)
    daily_log: list[DailyLogRow] = Field(default_factory=list)
    panels: dict[str, PanelValues] = Field(default_factory=dict)

    declared_monthly_total: Decimal | None = None
    """The workbook's own `APPROVED MONTHLY TOTAL`. Cross-checked, never trusted."""

    findings: list[Finding] = Field(default_factory=list)
    """Structural findings only in Phase 1B: unknown columns and skipped sections."""
