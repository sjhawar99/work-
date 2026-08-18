"""Typed configuration.

`config/*.yaml` is policy; this module is the schema that policy must satisfy. Every model
forbids unknown keys, so a typo in a config file fails loudly at load rather than
silently disabling a rule.

Two frozen decisions are enforced here rather than at build time, because a config that
contradicts them should never load at all:

* `BROAD` may not appear in `keywords.allowed_positive_match_types` (Decision A3).
* `account.monthly_budget_tolerance` may not be negative (Decision A2 wants exactness;
  rounding lives in `daily_budget_rounding_decimals`).
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

MatchType = Literal["EXACT", "PHRASE", "BROAD"]
NegativeLevel = Literal["ACCOUNT", "SHARED_LIST", "CAMPAIGN", "AD_GROUP"]
CallAssetLevel = Literal["AD_GROUP", "CAMPAIGN", "ACCOUNT"]


class ConfigError(Exception):
    """A configuration file is missing, unreadable, or does not satisfy the schema."""


class Strict(BaseModel):
    """Base model: unknown keys are an error, not a shrug."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- rules.yaml


class AccountRules(Strict):
    currency: str
    monthly_budget: Decimal
    monthly_budget_tolerance: Decimal
    daily_budget_rounding_decimals: int
    days_per_month: Decimal
    expected_campaign_count: int
    expected_ad_group_count: int
    primary_domain: str
    timezone: str

    @field_validator("monthly_budget_tolerance")
    @classmethod
    def _tolerance_is_not_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("monthly_budget_tolerance cannot be negative")
        return value


class WorkbookRules(Strict):
    """The canonical workbook is a Google Sheet; the .xlsx is an export artifact."""

    source: Literal["google_sheet_export"]
    """The only legal production source. `xlsx_native` was removed (Decision D3):

    the canonical human source is the Google Sheet and the compiler input is its export.
    Synthetic .xlsx test fixtures are built by `tests/fixtures/build_fixtures.py` and do
    not need a production mode of their own.
    """
    canonical_source_is_google_sheet: bool
    export_is_read_only_artifact: bool
    export_staleness_warning_days: int
    staleness_check_is_advisory_only: bool
    print_mtime_in_reports: bool


class NamingRules(Strict):
    campaign_pattern: str
    ad_group_pattern: str


class KeywordRules(Strict):
    allowed_positive_match_types: list[MatchType]
    allowed_negative_match_types: list[MatchType]
    max_ad_groups_per_keyword: int
    min_keywords_per_ad_group: int
    max_keyword_chars: int
    verify_copy_paste_column: bool

    @field_validator("allowed_positive_match_types")
    @classmethod
    def _no_broad_positives(cls, value: list[MatchType]) -> list[MatchType]:
        if "BROAD" in value:
            raise ValueError(
                "BROAD is not permitted as a positive match type (Decision A3, guardrail §18.5)"
            )
        return value


class SharedList(Strict):
    applies_to: list[str]


class NegativeRules(Strict):
    collision_check: bool
    allowed_levels: list[NegativeLevel]
    use_shared_lists: bool
    account_lists: list[str]
    shared_lists: dict[str, SharedList]
    campaign_scope_aliases: dict[str, list[str]]
    """Short name → exact campaign names. Explicit map; never substring matching."""
    campaign_sets: list[str]
    ad_group_sets: list[str]


class LengthRule(Strict):
    min: int | None = None
    max: int | None = None
    max_chars: int


class AdRules(Strict):
    headlines: LengthRule
    descriptions: LengthRule
    paths: LengthRule
    approved_asset_statuses: list[str] = Field(default_factory=lambda: ["APPROVED"])
    require_resolved_call_asset: bool
    require_call_asset_schedule: bool
    forbid_emoji: bool
    forbid_double_spaces: bool
    allowed_all_caps_tokens: list[str]


class CallAssetNumber(Strict):
    """A call number and the hours it is staffed."""

    number: str | None = None
    schedule: str | None = None


class CallAssetOverrides(Strict):
    """Exceptions to the campaign-level number, keyed by name."""

    ad_groups: dict[str, CallAssetNumber] = Field(default_factory=dict)
    campaigns: dict[str, CallAssetNumber] = Field(default_factory=dict)


class CallAssetRules(Strict):
    """How to resolve a call asset. The campaign-level number lives in the workbook."""

    resolution_order: list[CallAssetLevel]
    overrides: CallAssetOverrides = Field(default_factory=CallAssetOverrides)
    account_default: CallAssetNumber = Field(default_factory=CallAssetNumber)
    placeholder_tokens: list[str]
    placeholder_blocks_ready_build: bool


class LandingPageRules(Strict):
    base_url: str
    allowed_domains: list[str]
    extra_allowed_domains: list[str]
    max_url_chars: int
    require_https: bool
    check_http: bool
    allowed_status: list[int]
    follow_redirects: bool
    max_redirect_depth: int
    final_url_must_be_allowed_domain: bool
    googleadsbot_retry: bool
    googleadsbot_user_agent: str
    record_latency: bool
    timeout_seconds: int
    retries: int
    unknown_blocks_ready_build: bool
    one_landing_page_per_ad_group: bool


class UtmRules(Strict):
    required: bool
    recommended: list[str]


class TrackingTemplateRules(Strict):
    required: bool
    require_lpurl_if_present: bool


class TrackingRules(Strict):
    require_auto_tagging: bool
    preserve_gclid: bool
    require_conversion_goal: bool
    require_primary_conversion_selected_for_bidding: bool
    utm_params: UtmRules
    tracking_template: TrackingTemplateRules


class SettingsRules(Strict):
    search_partners_allowed: bool
    display_expansion_allowed: bool
    require_location_targets: bool
    require_language_targets: bool


class WatchdogThresholds(Strict):
    """Every threshold is nullable and null in Stage 1.

    `None` means "we have no Apex data yet". A validator must never invent a default for
    a null threshold — it emits a rank-and-review finding instead (spec §13.3).
    """

    junk_min_impressions: int | None
    junk_max_ctr: Decimal | None
    concentration_spend_share: Decimal | None
    held_demand_min_conversions: int | None


class WatchdogRules(Strict):
    input_dir: str
    cadence: str
    lookback_days: int
    owner: str
    thresholds: WatchdogThresholds
    concentration_mode: Literal["rank_and_review", "threshold"]
    learn_thresholds_after_days: int
    column_aliases: dict[str, list[str]]


class DriftRules(Strict):
    critical_fields: list[str]
    warning_fields: list[str]


class PrivacyRules(Strict):
    mask_in_generated_reports: list[str]
    raw_search_terms_allowed_in: list[str]
    raw_search_terms_forbidden_in: list[str]


class Rules(Strict):
    """`config/rules.yaml` — the enforcement policy."""

    version: int
    account: AccountRules
    workbook: WorkbookRules
    naming: NamingRules
    keywords: KeywordRules
    negatives: NegativeRules
    ads: AdRules
    call_assets: CallAssetRules
    landing_pages: LandingPageRules
    tracking: TrackingRules
    settings: SettingsRules
    watchdog: WatchdogRules
    drift: DriftRules
    privacy: PrivacyRules


# ----------------------------------------------------------------- workbook_schema.yaml


class SchemaMatching(Strict):
    case_sensitive: bool
    collapse_whitespace: bool
    strip_punctuation: bool
    blank_rows_end_section: int
    header_row_follows_banner: bool
    null_tokens: list[str]


class ScopeParsing(Strict):
    account: str
    ad_group: str
    campaign: str
    shared_list: str
    shared_list_campaign_separator: str
    shared_list_uses_short_names: bool


class Discriminator(Strict):
    column: str
    values: dict[str, str]


class SectionSpec(Strict):
    """One logical section: which sheet, which banner, which columns.

    `seen_at_row` is recorded for human reference only. Using it in code is a bug —
    sections are found by header text (spec §4.3).
    """

    sheet: str
    banner: str | None = None
    banner_match: Literal["exact", "prefix"] = "exact"
    seen_at_row: int | None = None
    required_columns: list[str] = Field(default_factory=list)
    optional_columns: list[str] = Field(default_factory=list)
    required: bool = True
    parse: bool = True
    shape: Literal["long", "wide"] = "long"
    headline_columns: str | None = None
    description_columns: str | None = None
    value_is_path: bool = False
    allow_unknown_columns: bool = False
    """True for sections where free-text notes columns are expected.

    Everywhere else a populated column nobody declared is a BLOCKER: the newer rule that
    nothing unclassified may disappear outranks the older tolerance for notes columns, and
    a build-critical section is exactly where a quietly ignored `Audience exclusion`
    column would do damage.
    """
    trailing_total_label: str | None = None
    discriminator: Discriminator | None = None
    scope_parsing: ScopeParsing | None = None


class CrossCheckPanel(Strict):
    sheet: str
    seen_at_row: int | None = None
    fields: list[str]


class WorkbookSchema(Strict):
    """`config/workbook_schema.yaml` — where each section lives in the four sheets."""

    version: int
    sheets: dict[str, str]
    matching: SchemaMatching
    sections: dict[str, SectionSpec]
    cross_check_panels: dict[str, CrossCheckPanel]

    @field_validator("sheets")
    @classmethod
    def _exactly_four_sheets(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) != 4:
            raise ValueError(
                f"expected exactly 4 sheets (Decision A1), found {len(value)}: {sorted(value)}"
            )
        return value


# ------------------------------------------------------------------- editor_schema.yaml


class CsvDialect(Strict):
    encoding: str
    line_terminator: str
    quoting: Literal["minimal", "all", "none"]


class ColumnMap(Strict):
    model_field: str
    editor_column: str
    required: bool
    transform: str | None = None


class EntityMap(Strict):
    file: str
    columns: list[ColumnMap]
    manual_only: list[str] = Field(default_factory=list)
    """Fields a human sets in the Google Ads UI, listed in MANUAL_STEPS.md."""
    documentation_only: list[str] = Field(default_factory=list)
    """Workbook notes that were never account configuration."""


class NegativeArtifact(Strict):
    file: str
    level: NegativeLevel
    columns: list[ColumnMap]
    import_support: str | None = None
    fallback: str | None = None


class VerifiedAgainst(Strict):
    """Provenance of the Editor export the column mappings were reconciled against."""

    export_date: str | None
    editor_version: str | None
    source_sha256: str | None
    reconciled_by: str | None

    def missing(self) -> list[str]:
        """Fields still unfilled. Empty means a real reconciliation was recorded."""
        return [name for name, value in self.model_dump().items() if not value]


Destination = Literal["editor", "manual_steps"]


class EditorSchema(Strict):
    """`config/editor_schema.yaml` — model fields to Google Ads Editor CSV columns."""

    version: int
    verified: bool
    """False until every column name is reconciled against a real Editor export.

    While false a build can never be READY (spec §10.5). `READY` has to mean
    *import-ready*, not *the compiler's own logic passed* — one unverified external
    contract is enough to make the difference matter.
    """
    verified_against: VerifiedAgainst
    inventory: dict[str, Destination]
    """Every compiled record type and where it goes. Missing entries block (EXP-002)."""

    @model_validator(mode="after")
    def _verification_requires_provenance(self) -> EditorSchema:
        """`verified: true` must say what it was verified against.

        Prose asking a human to fill these in is not enforcement: `verified: true` with
        four nulls loaded happily and produced READY builds, which defeats the point of
        recording provenance at all. Config now refuses to load.
        """
        if not self.verified:
            return self

        if missing := self.verified_against.missing():
            raise ValueError(
                "verified: true requires complete verified_against provenance; missing: "
                f"{sorted(missing)}"
            )

        digest = self.verified_against.source_sha256 or ""
        if not SHA256_PATTERN.fullmatch(digest):
            raise ValueError(
                f"verified_against.source_sha256 must be 64 hex characters, got {digest!r}"
            )
        return self

    csv: CsvDialect
    entities: dict[str, EntityMap]
    manual_only: list[str]
    negative_artifacts: dict[str, NegativeArtifact]

    @field_validator("negative_artifacts")
    @classmethod
    def _four_scopes_preserved(
        cls, value: dict[str, NegativeArtifact]
    ) -> dict[str, NegativeArtifact]:
        levels = {artifact.level for artifact in value.values()}
        expected = {"ACCOUNT", "SHARED_LIST", "CAMPAIGN", "AD_GROUP"}
        if levels != expected:
            missing = sorted(expected - levels)
            raise ValueError(
                f"negative export must preserve all four scopes (Decision A4); missing: {missing}"
            )
        return value


# ------------------------------------------------------------------------------ loading


class Config(Strict):
    """Everything loaded from `config/`, with the hash of each file for the manifest."""

    rules: Rules
    workbook_schema: WorkbookSchema
    editor_schema: EditorSchema
    sources: dict[str, Path]
    hashes: dict[str, str]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return loaded


def _describe(path: Path, error: ValidationError) -> str:
    lines = [f"{path}: {error.error_count()} problem(s)"]
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "(root)"
        lines.append(f"  {location}: {item['msg']}")
    return "\n".join(lines)


def load_config(config_dir: Path) -> Config:
    """Load and validate every config file. Raises `ConfigError` naming the exact key."""
    from apex_ads.util.hashing import sha256_file

    files = {
        "rules": config_dir / "rules.yaml",
        "workbook_schema": config_dir / "workbook_schema.yaml",
        "editor_schema": config_dir / "editor_schema.yaml",
    }
    models: dict[str, type[Strict]] = {
        "rules": Rules,
        "workbook_schema": WorkbookSchema,
        "editor_schema": EditorSchema,
    }

    parsed: dict[str, Any] = {}
    for name, path in files.items():
        payload = _read_yaml(path)
        try:
            parsed[name] = models[name].model_validate(payload)
        except ValidationError as exc:
            raise ConfigError(_describe(path, exc)) from exc

    return Config(
        rules=parsed["rules"],
        workbook_schema=parsed["workbook_schema"],
        editor_schema=parsed["editor_schema"],
        sources=dict(files),
        hashes={name: sha256_file(path) for name, path in files.items()},
    )
