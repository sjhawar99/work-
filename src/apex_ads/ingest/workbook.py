"""Turning the four-sheet workbook into a typed `WorkbookBundle`.

Phase 1B reads; it does not judge. The only findings produced here are structural
(unrecognised columns, skipped sections). Business rules — budgets, collisions, ad copy —
arrive with the validator framework in Phase 2.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from apex_ads.ingest import grid
from apex_ads.ingest.coerce import Reader
from apex_ads.ingest.errors import (
    CellCoercionError,
    MissingSectionError,
    UnknownRegistryTypeError,
)
from apex_ads.ingest.naming import Normaliser
from apex_ads.ingest.scope import ScopeParser
from apex_ads.ingest.sections import Section, find
from apex_ads.models.config import SectionSpec, WorkbookSchema
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import (
    AdAsset,
    AdGroupBuild,
    AssetKind,
    BlockingAction,
    CallAssetEntry,
    CampaignSettings,
    DailyLogRow,
    Keyword,
    LandingPageBrief,
    MeasurementContractItem,
    Negative,
    PanelValues,
    ResponsiveSearchAd,
    RunningAction,
    Scope,
    SupportingAsset,
    WorkbookBundle,
)
from apex_ads.policy import MATCH_TYPES, MODIFIED_BROAD_ALIASES
from apex_ads.util.text import is_null_token, normalise_text

SKIPPED_SECTION_RULE = "ING-101"
MAX_RSA_ASSETS = 30


def _match_type(reader: Reader, column: str) -> tuple[str, str]:
    """Return `(normalised, raw)`. `Modified Broad` becomes PHRASE (Decision A3)."""
    raw = reader.text(column)
    key = raw.strip().casefold()
    if key in MODIFIED_BROAD_ALIASES:
        return "PHRASE", raw
    if key in MATCH_TYPES:
        return MATCH_TYPES[key], raw
    raise CellCoercionError(
        sheet=reader.section.sheet,
        section=reader.section.name,
        row=reader.row.number,
        column=column,
        value=raw,
        target="a match type (Exact, Phrase or Broad)",
    )


def _copy_paste_expected(text: str, match_type: str) -> str:
    """Regenerate the workbook's derived `COPY / PASTE VALUE` (KW-009)."""
    if match_type == "PHRASE":
        return f'"{text}"'
    if match_type == "EXACT":
        return f"[{text}]"
    return text


def _assets(reader: Reader, kind: AssetKind, pattern: str | None) -> list[AdAsset]:
    if pattern is None:
        return []
    assets: list[AdAsset] = []
    for _, header in reader.section.columns.matching(pattern, MAX_RSA_ASSETS):
        text = reader.text(header)
        if not text:
            continue
        position = int("".join(character for character in header if character.isdigit()))
        assets.append(AdAsset(kind=kind, position=position, text=text, column=header))
    return sorted(assets, key=lambda asset: asset.position)


class WorkbookParser:
    """Parses one workbook against a `workbook_schema.yaml`."""

    def __init__(self, schema: WorkbookSchema) -> None:
        self.schema = schema
        self.blank_run = schema.matching.blank_rows_end_section
        self.normaliser = Normaliser.from_schema(schema.matching)

    # ------------------------------------------------------------------- helpers
    def _banners_on(self, sheet: str) -> tuple[str, ...]:
        return tuple(
            spec.banner
            for spec in self.schema.sections.values()
            if spec.sheet == sheet and spec.banner
        )

    def _section(self, book: grid.Workbook, name: str) -> tuple[Section, list[Finding]]:
        spec: SectionSpec = self.schema.sections[name]
        sheet = book.sheet(spec.sheet)
        return find(
            sheet,
            name,
            spec,
            blank_run=self.blank_run,
            normaliser=self.normaliser,
            other_banners=self._banners_on(spec.sheet),
        )

    def _optional_section(
        self, book: grid.Workbook, name: str, findings: list[Finding]
    ) -> Section | None:
        """Locate a section declared `required: false`.

        **Optional means "absence is permitted". It does not mean "broken data is
        ignored."** Only `MissingSectionError` — the section genuinely is not in the
        workbook — returns `None` with an INFO. Every other structural failure (a
        misspelled required heading, a duplicated column, an uncoercible cell) propagates
        and blocks the build.

        This caught every exception once, and the consequence was the exact fail-through
        the `CALL ASSET REGISTRY` was invented to prevent: type `Call phone no.` instead of
        `Call phone number` and the section a human had deliberately filled in was reported
        as "not read", the registry came back empty, and the resolver fell through to the
        campaign row. The operator's override silently did not happen — reported as an
        INFO saying "None needed while the section is optional."

        A present-but-malformed section is not an absent one. Absent means the human made
        no claim; malformed means they made one the machine could not read, and the second
        is never safe to answer with a default.
        """
        spec = self.schema.sections[name]
        try:
            section, section_findings = self._section(book, name)
        except MissingSectionError:
            findings.append(
                Finding(
                    rule_id=SKIPPED_SECTION_RULE,
                    severity=Severity.INFO,
                    message=f"optional section {name!r} is not present in this workbook",
                    sheet=spec.sheet,
                    section=name,
                    remedy="None needed. The section is optional and absent, which the "
                    "compiler reads as 'no entries', not as 'unknown'.",
                )
            )
            return None
        findings.extend(section_findings)
        return section

    # -------------------------------------------------------------------- parse
    def parse(self, path: Path) -> WorkbookBundle:
        """Read the workbook and build the bundle. Structural problems raise."""
        book = grid.load(path)
        findings: list[Finding] = []

        blocking, running = self._actions(book, findings)
        campaigns, declared_total = self._campaigns(book, findings)
        ad_groups = self._ad_groups(book, findings)
        call_asset_registry = self._call_asset_registry(book, findings)
        landing_pages = self._landing_pages(book, findings)
        assets = self._supporting_assets(book, findings)
        measurement = self._measurement(book, findings)
        ads = self._ads(book, findings)
        keywords, negatives = self._registry(book, findings)
        daily = self._daily(book, findings)

        return WorkbookBundle(
            source_path=path,
            source_sha256=book.sha256,
            source_mtime=book.mtime,
            blocking_actions=blocking,
            running_actions=running,
            campaigns=campaigns,
            ad_groups=ad_groups,
            landing_pages=landing_pages,
            supporting_assets=assets,
            call_asset_registry=call_asset_registry,
            measurement_contract=measurement,
            ads=ads,
            keywords=keywords,
            negatives=negatives,
            daily_log=daily,
            panels=self._panels(book),
            declared_monthly_total=declared_total,
            findings=findings,
        )

    # ---------------------------------------------------------------- 01 ACTIONS
    def _actions(
        self, book: grid.Workbook, findings: list[Finding]
    ) -> tuple[list[BlockingAction], list[RunningAction]]:
        blocking_section, blocking_findings = self._section(book, "actions_blocking")
        findings.extend(blocking_findings)
        blocking = [
            BlockingAction(
                **Reader(blocking_section, row).provenance,
                number=Reader(blocking_section, row).optional_int("#"),
                task=Reader(blocking_section, row).text("Task / problem"),
                type=Reader(blocking_section, row).text("Type"),
                owner=Reader(blocking_section, row).text("Owner"),
                due=Reader(blocking_section, row).optional_date("Due"),
                status=Reader(blocking_section, row).text("Status"),
                severity=Reader(blocking_section, row).text("Severity"),
                done_when=Reader(blocking_section, row).text("Done when"),
            )
            for row in blocking_section.rows
        ]

        running_section, running_findings = self._section(book, "actions_running")
        findings.extend(running_findings)
        running = []
        for row in running_section.rows:
            reader = Reader(running_section, row)
            running.append(
                RunningAction(
                    **reader.provenance,
                    number=reader.optional_int("#"),
                    date_raised=reader.optional_date("Date raised"),
                    task=reader.text("Task or problem"),
                    type=reader.text("Type"),
                    required_action=reader.text("Required action / next step"),
                    owner=reader.text("Owner"),
                    due=reader.optional_date("Due"),
                    status=reader.text("Status"),
                    severity=reader.text("Severity"),
                    blocked_by=reader.text("Blocked by"),
                    recurring=reader.text("Recurring?"),
                )
            )
        return blocking, running

    # ------------------------------------------------------------------ 02 BUILD
    def _campaigns(
        self, book: grid.Workbook, findings: list[Finding]
    ) -> tuple[list[CampaignSettings], Decimal | None]:
        section, section_findings = self._section(book, "campaigns")
        findings.extend(section_findings)

        campaigns = []
        for row in section.rows:
            reader = Reader(section, row)
            campaigns.append(
                CampaignSettings(
                    **reader.provenance,
                    number=reader.optional_int("#"),
                    name=reader.text("Exact campaign name"),
                    monthly_budget=reader.decimal("Monthly budget"),
                    avg_daily_budget=reader.decimal("Avg daily budget"),
                    campaign_type=reader.text("Campaign type"),
                    networks=reader.text("Networks"),
                    geo=reader.text("Geo"),
                    location_option=reader.text("Location option"),
                    languages=reader.text("Languages"),
                    launch_bidding=reader.text("Launch bidding"),
                    legacy_avg_cpc=reader.optional_decimal("Legacy avg CPC (context)")
                    if section.columns.has("Legacy avg CPC (context)")
                    else None,
                    launch_max_cpc=reader.optional_decimal("Launch Max CPC limit"),
                    bidding_review_gate=reader.text("Bidding review gate")
                    if section.columns.has("Bidding review gate")
                    else "",
                    primary_conversion=reader.text("Primary conversion / bidding goal"),
                    secondary_conversions=reader.text("Secondary conversions")
                    if section.columns.has("Secondary conversions")
                    else "",
                    call_phone_number=reader.text("Call phone number"),
                    call_schedule=reader.text("Call schedule / reporting"),
                    automation_guardrails=reader.text("Automation guardrails"),
                    status=reader.text("Status"),
                    why=reader.text("Why this exists")
                    if section.columns.has("Why this exists")
                    else "",
                    launch_date=reader.optional_date("Launch date")
                    if section.columns.has("Launch date")
                    else None,
                    owner=reader.text("Owner") if section.columns.has("Owner") else "",
                )
            )

        total: Decimal | None = None
        if not is_null_token(section.trailing_total):
            from apex_ads.util.currency import parse_currency

            total = parse_currency(section.trailing_total)
        return campaigns, total

    def _ad_groups(self, book: grid.Workbook, findings: list[Finding]) -> list[AdGroupBuild]:
        section, section_findings = self._section(book, "ad_groups")
        findings.extend(section_findings)

        groups = []
        for row in section.rows:
            reader = Reader(section, row)
            groups.append(
                AdGroupBuild(
                    **reader.provenance,
                    number=reader.optional_int("#"),
                    campaign=reader.text("Campaign"),
                    name=reader.text("Exact ad group name"),
                    what_it_owns=reader.text("What it owns")
                    if section.columns.has("What it owns")
                    else "",
                    dominant_intent=reader.text("Dominant intent"),
                    planned_landing_page=reader.text("Planned landing page"),
                    call_asset=reader.text("Call asset"),
                    keyword_source=reader.text("Keyword source")
                    if section.columns.has("Keyword source")
                    else "",
                    negative_lists=reader.text_list("Negative lists / routing"),
                    negative_lists_raw=reader.text("Negative lists / routing"),
                    rsa=reader.text("RSA"),
                    status=reader.text("Status"),
                    notes=reader.text("Notes") if section.columns.has("Notes") else "",
                )
            )
        return groups

    def _call_asset_registry(
        self, book: grid.Workbook, findings: list[Finding]
    ) -> list[CallAssetEntry]:
        """The optional call-asset registry. Absent means "no exceptions", never "unknown".

        Every level that can supply a phone number is read here, because a phone number is
        an approved account value and approved account values live in the workbook.
        """
        section = self._optional_section(book, "call_asset_registry", findings)
        if section is None:
            return []

        entries = []
        for row in section.rows:
            reader = Reader(section, row)
            optional = section.columns.has
            entries.append(
                CallAssetEntry(
                    **reader.provenance,
                    level=reader.text("Level").strip().upper().replace(" ", "_"),
                    campaign=reader.text("Campaign") if optional("Campaign") else "",
                    ad_group=reader.text("Ad group") if optional("Ad group") else "",
                    number=reader.text("Call phone number"),
                    schedule=reader.text("Call schedule / reporting"),
                    status=reader.text("Status") if optional("Status") else "",
                    why=reader.text("Why") if optional("Why") else "",
                )
            )
        return entries

    def _landing_pages(
        self, book: grid.Workbook, findings: list[Finding]
    ) -> list[LandingPageBrief]:
        section, section_findings = self._section(book, "landing_pages")
        findings.extend(section_findings)

        pages = []
        for row in section.rows:
            reader = Reader(section, row)
            optional = section.columns.has
            pages.append(
                LandingPageBrief(
                    **reader.provenance,
                    ad_group=reader.text("Ad group"),
                    planned_url=reader.text("Planned URL"),
                    user_question=reader.text("User question") if optional("User question") else "",
                    hero_must_answer=reader.text("Hero must answer")
                    if optional("Hero must answer")
                    else "",
                    proof_trust=reader.text("Proof / trust") if optional("Proof / trust") else "",
                    primary_cta=reader.text("Primary CTA") if optional("Primary CTA") else "",
                    must_include=reader.text("Must include") if optional("Must include") else "",
                    tracking=reader.text("Tracking") if optional("Tracking") else "",
                    status=reader.text("Status"),
                )
            )
        return pages

    def _supporting_assets(
        self, book: grid.Workbook, findings: list[Finding]
    ) -> list[SupportingAsset]:
        section, section_findings = self._section(book, "supporting_assets")
        findings.extend(section_findings)

        assets = []
        for row in section.rows:
            reader = Reader(section, row)
            optional = section.columns.has
            assets.append(
                SupportingAsset(
                    **reader.provenance,
                    asset_type=reader.text("Asset type"),
                    scope=reader.text("Scope"),
                    text_header=reader.text("Text / Header"),
                    url_values=reader.text("URL / Values") if optional("URL / Values") else "",
                    description_1=reader.text("Description 1") if optional("Description 1") else "",
                    description_2=reader.text("Description 2") if optional("Description 2") else "",
                    status=reader.text("Status"),
                )
            )
        return assets

    def _measurement(
        self, book: grid.Workbook, findings: list[Finding]
    ) -> list[MeasurementContractItem]:
        section, section_findings = self._section(book, "measurement_contract")
        findings.extend(section_findings)

        items = []
        for row in section.rows:
            reader = Reader(section, row)
            optional = section.columns.has
            items.append(
                MeasurementContractItem(
                    **reader.provenance,
                    item=reader.text("Item"),
                    final_rule=reader.text("Final rule"),
                    launch_status=reader.text("Launch status"),
                    owner=reader.text("Owner"),
                    qa_evidence=reader.text("QA evidence") if optional("QA evidence") else "",
                    source_note=reader.text("Source / note") if optional("Source / note") else "",
                )
            )
        return items

    def _ads(self, book: grid.Workbook, findings: list[Finding]) -> list[ResponsiveSearchAd]:
        section, section_findings = self._section(book, "rsa")
        findings.extend(section_findings)

        ads = []
        for row in section.rows:
            reader = Reader(section, row)
            ads.append(
                ResponsiveSearchAd(
                    **reader.provenance,
                    campaign=reader.text("Campaign"),
                    ad_group=reader.text("Ad group"),
                    headlines=_assets(reader, "HEADLINE", section.spec.headline_columns),
                    descriptions=_assets(reader, "DESCRIPTION", section.spec.description_columns),
                )
            )
        return ads

    # --------------------------------------------------------------- 03 KEYWORDS
    def _registry(
        self, book: grid.Workbook, findings: list[Finding]
    ) -> tuple[list[Keyword], list[Negative]]:
        section, section_findings = self._section(book, "keyword_registry")
        findings.extend(section_findings)

        discriminator = section.spec.discriminator
        scope_spec = section.spec.scope_parsing
        if discriminator is None or scope_spec is None:
            raise ValueError("keyword_registry needs both discriminator and scope_parsing")
        scope_parser = ScopeParser(scope_spec)

        wanted = {value.strip().casefold(): key for key, value in discriminator.values.items()}
        keywords: list[Keyword] = []
        negatives: list[Negative] = []

        for row in section.rows:
            reader = Reader(section, row)
            kind = wanted.get(reader.text(discriminator.column).strip().casefold())
            if kind is None:
                raise UnknownRegistryTypeError(
                    sheet=section.sheet,
                    section=section.name,
                    row=row.number,
                    value=reader.text(discriminator.column),
                    allowed=sorted(discriminator.values.values()),
                )

            campaign = reader.optional_text("Campaign")
            ad_group = reader.optional_text("Ad group")
            match_type, match_type_raw = _match_type(reader, "Match type")
            text = reader.text("Keyword text")
            scope: Scope = scope_parser.parse(
                reader.raw("Scope"),
                sheet=section.sheet,
                section=section.name,
                row=row.number,
                campaign=campaign,
                ad_group=ad_group,
            )
            shared: dict[str, Any] = {
                **reader.provenance,
                "campaign": campaign,
                "ad_group": ad_group,
                "scope": scope,
                "match_type": match_type,
                "match_type_raw": match_type_raw,
                "text": text,
                "copy_paste_value": reader.text("COPY / PASTE VALUE"),
                "copy_paste_expected": _copy_paste_expected(text, match_type),
                "list_name": reader.optional_text("List name"),
                "status": reader.text("Status"),
                "why": reader.text("Why") if section.columns.has("Why") else "",
                "added_by": reader.text("Added by") if section.columns.has("Added by") else "",
                "added_on": reader.optional_date("Date") if section.columns.has("Date") else None,
            }
            if kind == "keyword":
                keywords.append(Keyword(**shared))
            else:
                negatives.append(Negative(**shared))

        return keywords, negatives

    # ------------------------------------------------------------------ 04 DAILY
    def _daily(self, book: grid.Workbook, findings: list[Finding]) -> list[DailyLogRow]:
        """Context and provenance only. Nothing here may influence a build decision."""
        section = self._optional_section(book, "daily_log", findings)
        if section is None:
            return []

        entries = []
        for row in section.rows:
            reader = Reader(section, row)
            optional = section.columns.has
            entries.append(
                DailyLogRow(
                    **reader.provenance,
                    date=reader.optional_date("Date"),
                    campaign=reader.text("Campaign"),
                    planned_daily_budget=reader.optional_decimal("Planned daily budget"),
                    spend=reader.optional_decimal("Spend") if optional("Spend") else None,
                    clicks=reader.optional_int("Clicks") if optional("Clicks") else None,
                    raw_leads=reader.text("Raw leads / calls")
                    if optional("Raw leads / calls")
                    else "",
                    breakage_check=reader.text("Breakage check")
                    if optional("Breakage check")
                    else "",
                    changed_today=reader.text("What we changed today (and who)")
                    if optional("What we changed today (and who)")
                    else "",
                    delivery_signal=reader.text("Delivery / raw-lead signal")
                    if optional("Delivery / raw-lead signal")
                    else "",
                    qualified_leads=reader.text("Qualified leads (backfill)")
                    if optional("Qualified leads (backfill)")
                    else "",
                    appointments=reader.text("Appointments (backfill)")
                    if optional("Appointments (backfill)")
                    else "",
                    attended_opd=reader.text("Attended OPD (backfill)")
                    if optional("Attended OPD (backfill)")
                    else "",
                )
            )
        return entries

    # -------------------------------------------------------------------- panels
    def _panels(self, book: grid.Workbook) -> dict[str, PanelValues]:
        """Read the dashboard panels the workbook states, for later cross-checking.

        Nothing consumes these yet. They exist so Phase 2 can recompute each figure and
        report disagreement rather than trusting the cell.
        """
        panels: dict[str, PanelValues] = {}
        for name, spec in self.schema.cross_check_panels.items():
            if spec.sheet not in book.sheets:
                continue
            wanted = {self.normaliser.key(field): field for field in spec.fields}
            values: dict[str, str] = {}
            for row in book.sheet(spec.sheet).rows:
                for position in range(len(row.cells)):
                    label = self.normaliser.key(row.text(position))
                    if label not in wanted:
                        continue
                    for follower in range(position + 1, len(row.cells)):
                        candidate = row.value(follower)
                        if not is_null_token(candidate):
                            values[wanted[label]] = normalise_text(str(candidate))
                            break
            panels[name] = PanelValues(sheet=spec.sheet, values=values)
        return panels


def parse_workbook(path: Path, schema: WorkbookSchema) -> WorkbookBundle:
    """Convenience wrapper: parse `path` against `schema`."""
    return WorkbookParser(schema).parse(path)
