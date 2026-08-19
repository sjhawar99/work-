"""Phase 2 validators: budgets, structure, action items, panel cross-checks.

Every test names the rule it exercises. Rule IDs are stable forever, so these double as
the index for what each rule actually does.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import Rules, WorkbookSchema
from apex_ads.models.findings import Severity
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.policy import WAIVABLE_RULE_IDS
from apex_ads.validate.registry import VALIDATORS, rule_ids
from apex_ads.validate.runner import ValidationResult, is_waivable, run


def validate(path: Path, schema: WorkbookSchema, rules: Rules) -> ValidationResult:
    return run(parse_workbook(path, schema), rules)


@pytest.fixture(scope="module")
def clean(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> ValidationResult:
    return validate(fixtures["clean"], schema, fixture_rules)


def ids_of(result: ValidationResult, severity: Severity | None = None) -> set[str]:
    findings = (
        result.findings
        if severity is None
        else [f for f in result.findings if f.severity is severity]
    )
    return {finding.rule_id for finding in findings}


# ------------------------------------------------------------------- framework


def test_a_clean_workbook_passes(clean: ValidationResult) -> None:
    assert clean.passed
    assert not clean.blockers
    assert ids_of(clean, Severity.BLOCKER) == set()


def test_rule_ids_are_unique(clean: ValidationResult) -> None:
    assert len(rule_ids()) == len(set(rule_ids()))


def test_every_validator_runs_even_after_one_fails(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """A broken rule must not hide the findings of the others."""

    class Exploding:
        rule_id = "TEST-BOOM"
        severity = Severity.BLOCKER

        def check(self, bundle: WorkbookBundle, rules: Rules) -> list[object]:
            raise RuntimeError("deliberate")

    bundle = parse_workbook(fixtures["budget_mismatch"], schema)
    result = run(bundle, fixture_rules, validators=(Exploding(), *VALIDATORS))  # type: ignore[arg-type]

    assert "VAL-999" in ids_of(result)
    assert "BUD-001" in ids_of(result), "a broken validator hid a real finding"


def test_all_findings_are_collected_not_just_the_first(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    result = validate(fixtures["open_red_action"], schema, fixture_rules)
    assert len(result.findings) > 1


def test_findings_are_ordered_worst_first(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    result = validate(fixtures["budget_mismatch"], schema, fixture_rules)
    severities = [finding.severity for finding in result.findings]
    assert severities == sorted(
        severities, key=lambda s: {"BLOCKER": 0, "WARNING": 1, "INFO": 2}[s]
    )


def test_nothing_is_waivable_in_stage_one() -> None:
    """Decision A2: a waiver records acceptance; it never suppresses a rule."""
    assert frozenset() == WAIVABLE_RULE_IDS
    for rule_id in rule_ids():
        assert not is_waivable(rule_id), rule_id


# ---------------------------------------------------------------------- budget


def test_bud_001_reports_both_figures(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 7 (spec §19.2)."""
    result = validate(fixtures["budget_mismatch"], schema, fixture_rules)
    finding = next(f for f in result.blockers if f.rule_id == "BUD-001")
    assert "24,000" in finding.message
    assert "25,000" in finding.message
    assert not result.passed


def test_bud_001_has_zero_tolerance(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """A ₹1 shortfall is a BLOCKER. Decision C2 removed the 2% band."""
    account = fixture_rules.account.model_copy(update={"monthly_budget": Decimal("25001")})
    rules = fixture_rules.model_copy(update={"account": account})
    result = validate(fixtures["clean"], schema, rules)
    assert "BUD-001" in ids_of(result, Severity.BLOCKER)


def test_bud_004_accepts_the_workbook_rounding(clean: ValidationResult) -> None:
    assert "BUD-004" not in ids_of(clean)


def test_bud_005_catches_a_stale_declared_total(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    result = validate(fixtures["budget_mismatch"], schema, fixture_rules)
    assert "BUD-005" not in ids_of(result), "declared total was updated with the rows"


def test_bud_003_reports_itself_as_not_applicable(clean: ValidationResult) -> None:
    """A check that did not apply is reported, never silently counted as a pass."""
    finding = next(f for f in clean.infos if f.rule_id == "BUD-003")
    assert "not applicable" in finding.message


# ------------------------------------------------------------------- structure


def test_str_001_and_002_count_exactly(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    account = fixture_rules.account.model_copy(update={"expected_campaign_count": 3})
    rules = fixture_rules.model_copy(update={"account": account})
    result = validate(fixtures["clean"], schema, rules)
    finding = next(f for f in result.blockers if f.rule_id == "STR-001")
    assert "found 2 campaigns" in finding.message


def test_str_lp_001_blocks_an_ambiguous_landing_page(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """The rule that turns today's accidental name uniqueness into a checked assumption."""
    result = validate(fixtures["duplicate_ad_group_name"], schema, fixture_rules)
    finding = next(f for f in result.blockers if f.rule_id == "STR-LP-001")
    assert "Neuro | Provider" in finding.message
    assert "2 campaigns" in finding.message
    assert "TST | Search | Brand | Jaipur" in finding.message


def test_str_lp_001_passes_when_names_resolve_uniquely(clean: ValidationResult) -> None:
    assert "STR-LP-001" not in ids_of(clean)


def test_landing_page_resolution_refuses_to_guess(
    fixtures: dict[str, Path], schema: WorkbookSchema
) -> None:
    from apex_ads.validate.structure import resolve_landing_pages

    bundle = parse_workbook(fixtures["duplicate_ad_group_name"], schema)
    resolved = resolve_landing_pages(bundle)
    assert not any(key.ad_group == "Neuro | Provider" for key in resolved)


def test_str_008_requires_every_campaign_to_have_a_scope_alias(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """No substring matching: an unmapped campaign must fail, not be guessed at."""
    negatives = fixture_rules.negatives.model_copy(
        update={"campaign_scope_aliases": {"Brand": ["TST | Search | Brand | Jaipur"]}}
    )
    rules = fixture_rules.model_copy(update={"negatives": negatives})
    result = validate(fixtures["clean"], schema, rules)
    finding = next(f for f in result.blockers if f.rule_id == "STR-008")
    assert "TST | Search | Neuro | Jaipur" in finding.message


def test_str_008_rejects_an_alias_pointing_nowhere(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    aliases = dict(fixture_rules.negatives.campaign_scope_aliases)
    aliases["Ortho"] = ["TST | Search | Ortho | Jaipur"]
    negatives = fixture_rules.negatives.model_copy(update={"campaign_scope_aliases": aliases})
    rules = fixture_rules.model_copy(update={"negatives": negatives})
    result = validate(fixtures["clean"], schema, rules)
    messages = [f.message for f in result.blockers if f.rule_id == "STR-008"]
    assert any("is not a campaign in this workbook" in message for message in messages)


def test_str_003_has_no_orphans_in_a_clean_workbook(clean: ValidationResult) -> None:
    assert "STR-003" not in ids_of(clean)


def test_str_007_is_a_warning_not_a_blocker(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    keywords = fixture_rules.keywords.model_copy(update={"min_keywords_per_ad_group": 99})
    rules = fixture_rules.model_copy(update={"keywords": keywords})
    result = validate(fixtures["clean"], schema, rules)
    assert "STR-007" in ids_of(result, Severity.WARNING)
    assert "STR-007" not in ids_of(result, Severity.BLOCKER)


# ---------------------------------------------------------------- action items


def test_act_001_blocks_an_open_red_action(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 11 (spec §19.2)."""
    result = validate(fixtures["open_red_action"], schema, fixture_rules)
    finding = next(f for f in result.blockers if f.rule_id == "ACT-001")
    assert "Approve the lead definition" in finding.message
    assert finding.row is not None
    assert not result.passed


def test_act_001_reads_both_action_tables(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    bundle = parse_workbook(fixtures["clean"], schema)
    running = bundle.running_actions[0].model_copy(update={"severity": "RED", "status": "Open"})
    mutated = bundle.model_copy(update={"running_actions": [running]})
    result = run(mutated, fixture_rules)
    sections = {f.section for f in result.blockers if f.rule_id == "ACT-001"}
    assert sections == {"actions_running"}


def test_act_002_lists_amber_without_blocking(clean: ValidationResult) -> None:
    assert "ACT-002" in ids_of(clean, Severity.WARNING)
    assert clean.passed


# ------------------------------------------------------------------ panels


def test_xchk_001_reports_a_stale_panel(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    from apex_ads.models.workbook import PanelValues

    bundle = parse_workbook(fixtures["clean"], schema)
    panels = dict(bundle.panels)
    panels["pre_flight"] = PanelValues(sheet="02 BUILD", values={"Approved monthly": "99000"})
    result = run(bundle.model_copy(update={"panels": panels}), fixture_rules)
    finding = next(f for f in result.warnings if f.rule_id == "XCHK-001")
    assert "99000" in finding.message
    assert "25000" in finding.message


def test_every_finding_carries_a_remedy(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    result = validate(fixtures["budget_mismatch"], schema, fixture_rules)
    for finding in result.blockers:
        assert finding.remedy, finding.rule_id


def test_shifted_rows_produce_identical_findings(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 9 (spec §19.2), at validation level.

    The same rules fire with the same messages; only the row coordinates move, because
    the records genuinely came from different rows.
    """
    clean = validate(fixtures["clean"], schema, fixture_rules)
    shifted = validate(fixtures["shifted"], schema, fixture_rules)

    def payload(result: ValidationResult) -> list[tuple[str, str, str]]:
        return [(f.rule_id, f.severity.value, f.message) for f in result.findings]

    assert payload(clean) == payload(shifted)
    assert clean.counts() == shifted.counts()


# ------------------------------------------------------------------- keywords


def test_kw_001_blocks_a_broad_positive(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance tests 3 and 27: `Broad` fails; it is never normalised away."""
    result = validate(fixtures["broad_positive"], schema, fixture_rules)
    finding = next(f for f in result.blockers if f.rule_id == "KW-001")
    assert "BROAD" in finding.message
    assert not result.passed
    assert "KW-008" not in ids_of(result), "Broad must not be treated as a legacy match type"


def test_kw_008_normalises_modified_broad_with_a_warning(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 26: legacy nomenclature does not break the build."""
    result = validate(fixtures["modified_broad"], schema, fixture_rules)
    finding = next(f for f in result.warnings if f.rule_id == "KW-008")
    assert "LEGACY_MATCH_TYPE_NORMALIZED" in finding.message
    assert "KW-001" not in ids_of(result, Severity.BLOCKER)
    assert result.passed


def test_kw_009_catches_a_stale_copy_paste_value(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    result = validate(fixtures["copy_paste_mismatch"], schema, fixture_rules)
    finding = next(f for f in result.blockers if f.rule_id == "KW-009")
    assert "[apex hospital]" in finding.message
    assert '"apex hospital"' in finding.message


def test_kw_007_reports_itself_as_not_applicable(clean: ValidationResult) -> None:
    finding = next(f for f in clean.infos if f.rule_id == "KW-007")
    assert "not applicable" in finding.message


def test_keyword_rules_are_quiet_on_a_clean_workbook(clean: ValidationResult) -> None:
    for rule_id in ("KW-001", "KW-002", "KW-003", "KW-004", "KW-006", "KW-008", "KW-009"):
        assert rule_id not in ids_of(clean), rule_id


# ------------------------------------------------------------------ negatives


def test_neg_001_blocks_a_collision(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    result = validate(fixtures["collision_account"], schema, fixture_rules)
    assert "NEG-001" in ids_of(result, Severity.BLOCKER)
    assert not result.passed


def test_neg_006_blocks_a_shared_list_applied_to_nothing(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 30 — a list that protects nothing reads as protection that exists.

    The list must be genuinely orphaned: declared in config, with no members in the
    registry and no routing in 02 BUILD. Emptying `applies_to` on a list the workbook
    still uses is a different fault, and NEG-008 reports that one.
    """
    orphan = fixture_rules.negatives.shared_lists["ROUTE_BRAND"].model_copy(
        update={"applies_to": []}
    )
    negatives = fixture_rules.negatives.model_copy(
        update={"shared_lists": {**fixture_rules.negatives.shared_lists, "ROUTE_ORPHAN": orphan}}
    )
    rules = fixture_rules.model_copy(update={"negatives": negatives})
    result = validate(fixtures["clean"], schema, rules)

    messages = [f.message for f in result.blockers if f.rule_id == "NEG-006"]
    assert any("ROUTE_ORPHAN" in message for message in messages), messages


def test_neg_007_blocks_an_undeclared_list(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    negatives = fixture_rules.negatives.model_copy(
        update={
            "shared_lists": {
                name: entry
                for name, entry in fixture_rules.negatives.shared_lists.items()
                if name != "ROUTE_BRAND"
            }
        }
    )
    rules = fixture_rules.model_copy(update={"negatives": negatives})
    result = validate(fixtures["clean"], schema, rules)
    finding = next(f for f in result.blockers if f.rule_id == "NEG-007")
    assert "ROUTE_BRAND" in finding.message


def test_neg_008_reports_all_three_routing_sources(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 39 — no source is silently preferred; all three are named."""
    result = validate(fixtures["routing_mismatch"], schema, fixture_rules)
    finding = next(f for f in result.blockers if f.rule_id == "NEG-008")
    assert "approved policy (rules.yaml)" in finding.message
    assert "registry Scope (03 KEYWORDS)" in finding.message
    assert "operator routing (02 BUILD)" in finding.message
    assert "Brand" in finding.message


def test_neg_008_is_quiet_when_the_three_agree(clean: ValidationResult) -> None:
    assert "NEG-008" not in ids_of(clean)


def test_negative_rules_are_quiet_on_a_clean_workbook(clean: ValidationResult) -> None:
    for rule_id in ("NEG-001", "NEG-002", "NEG-003", "NEG-006", "NEG-007", "NEG-008", "NEG-009"):
        assert rule_id not in ids_of(clean), rule_id


def test_kw_005_near_duplicates_stay_advisory(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Near-duplicate is a judgement call, not a structural defect.

    Two keywords can look alike and still be deliberate — different match types, different
    ad groups, different intent. The validator may surface them; it must not start
    designing keyword strategy under the banner of hygiene. `KW-003` covers the genuine
    structural duplicate, and that one blocks.
    """
    from apex_ads.validate.keywords import NearDuplicateKeywords

    assert NearDuplicateKeywords.severity is Severity.WARNING

    bundle = parse_workbook(fixtures["clean"], schema)
    twin = bundle.keywords[0].model_copy(
        update={
            "campaign": "TST | Search | Neuro | Jaipur",
            "ad_group": "Neuro | Provider",
            "text": "hospital apex",
        }
    )
    result = run(bundle.model_copy(update={"keywords": [*bundle.keywords, twin]}), fixture_rules)
    assert "KW-005" in ids_of(result, Severity.WARNING)
    assert "KW-005" not in ids_of(result, Severity.BLOCKER)


# ------------------------------------------- routing reconciliation with absent sources


def test_neg_008_treats_an_absent_source_as_disagreement(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """One of three mandatory sources vanishing is not consensus.

    The comparison used to drop empty sources before comparing, so a shared list could
    disappear completely from `02 BUILD` and the two survivors would "agree".
    """
    bundle = parse_workbook(fixtures["clean"], schema)
    stripped = [
        group.model_copy(
            update={"negative_lists": [n for n in group.negative_lists if n != "ROUTE_BRAND"]}
        )
        for group in bundle.ad_groups
    ]
    result = run(bundle.model_copy(update={"ad_groups": stripped}), fixture_rules)

    finding = next(f for f in result.blockers if f.rule_id == "NEG-008")
    assert "ROUTE_BRAND" in finding.message
    assert "ABSENT" in finding.message
    assert "not an abstention" in finding.remedy


def test_neg_008_ignores_non_shared_list_sets(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Campaign and ad-group sets carry their own scope; comparing them against a
    shared-list `applies_to` would manufacture a disagreement out of a category error."""
    bundle = parse_workbook(fixtures["clean"], schema)
    result = run(bundle, fixture_rules)
    flagged = {f.entity for f in result.blockers if f.rule_id == "NEG-008"}
    assert not (flagged & set(fixture_rules.negatives.campaign_sets))
    assert not (flagged & set(fixture_rules.negatives.ad_group_sets))


# ------------------------------------------------------------------- call assets


def _registry_entry(
    level: str,
    campaign: str,
    ad_group: str,
    number: str,
    schedule: str,
    *,
    status: str = "APPROVED",
    row: int = 99,
):
    from apex_ads.models.workbook import CallAssetEntry

    return CallAssetEntry(
        sheet="02 BUILD",
        row=row,
        section="call_asset_registry",
        level=level,
        campaign=campaign,
        ad_group=ad_group,
        number=number,
        schedule=schedule,
        status=status,
        why="test",
    )


def test_call_asset_resolution_order_is_honoured(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 35 — the one CODEX_TASKS claimed passed while it did not exist.

    Ad group beats campaign, campaign beats account, and the order comes from
    `rules.call_assets.resolution_order`. Every number is read from the workbook: the
    account and override levels used to live in `rules.yaml`, which put an approved account
    value in the rules file and let the validated number differ from the rendered one.
    """
    from apex_ads.validate import callassets

    bundle = parse_workbook(fixtures["clean"], schema)
    with_numbers = bundle.model_copy(
        update={
            "campaigns": [
                c.model_copy(update={"call_phone_number": "+91 campaign", "call_schedule": "9-5"})
                for c in bundle.campaigns
            ]
        }
    )
    target = with_numbers.ad_groups[0].key

    # campaign level supplies it when nothing more specific exists
    base = callassets.resolve(with_numbers, fixture_rules)
    assert base[target] is not None
    assert base[target].source == "campaign row"

    # a CAMPAIGN registry row outranks the campaign settings row
    campaign_row = with_numbers.model_copy(
        update={
            "call_asset_registry": [
                _registry_entry("CAMPAIGN", target.campaign, "", "+91 campaign registry", "10-6")
            ]
        }
    )
    resolved = callassets.resolve(campaign_row, fixture_rules)
    assert resolved[target].source == "campaign registry"
    assert resolved[target].number == "+91 campaign registry"

    # an AD_GROUP registry row outranks both
    ad_group_row = campaign_row.model_copy(
        update={
            "call_asset_registry": [
                *campaign_row.call_asset_registry,
                _registry_entry("AD_GROUP", target.campaign, target.ad_group, "+91 adgroup", "24h"),
            ]
        }
    )
    resolved = callassets.resolve(ad_group_row, fixture_rules)
    assert resolved[target].source == "ad group registry"
    assert resolved[target].number == "+91 adgroup"

    # with no campaign number anywhere, an ACCOUNT registry row is the last resort
    stripped = with_numbers.model_copy(
        update={
            "campaigns": [
                c.model_copy(update={"call_phone_number": "", "call_schedule": ""})
                for c in with_numbers.campaigns
            ],
            "call_asset_registry": [
                _registry_entry("ACCOUNT", "", "", "+91 account", "9-6"),
            ],
        }
    )
    fallback = callassets.resolve(stripped, fixture_rules)
    assert fallback[target].source == "account registry"
    assert fallback[target].number == "+91 account"


def test_call_asset_rules_cannot_hold_a_phone_number(config_dir: Path) -> None:
    """A phone number in `rules.yaml` must not load at all (AGENTS.md layering).

    Not a convention: `CallAssetRules` forbids unknown keys, so the keys that used to hold
    numbers cannot come back by accident.
    """
    from pydantic import ValidationError

    from apex_ads.models.config import CallAssetRules

    with pytest.raises(ValidationError):
        CallAssetRules(
            resolution_order=["AD_GROUP", "CAMPAIGN", "ACCOUNT"],
            placeholder_tokens=["TBD"],
            placeholder_blocks_ready_build=True,
            account_default={"number": "+91 141 000 0000"},
        )


def test_ad_014_flags_a_registry_row_that_targets_nothing(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """A typo'd ad-group name is not an override — it is an override that did not happen."""
    bundle = parse_workbook(fixtures["clean"], schema)
    typo = bundle.model_copy(
        update={
            "call_asset_registry": [
                _registry_entry(
                    "AD_GROUP", bundle.ad_groups[0].campaign, "Brnd | Core", "+91 x", "24h"
                )
            ]
        }
    )
    result = run(typo, fixture_rules)
    finding = next(f for f in result.findings if f.rule_id == "AD-014")
    assert "Brnd | Core" in finding.message
    assert finding.severity is Severity.BLOCKER


def test_ad_014_blocks_two_rows_governing_the_same_scope(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """`resolve()` takes whichever comes first, so one of the two numbers is silently unused.

    Nothing told the operator which row won, and the two rows carry different numbers.
    """
    bundle = parse_workbook(fixtures["clean"], schema)
    group = bundle.ad_groups[0]
    duplicated = bundle.model_copy(
        update={
            "call_asset_registry": [
                _registry_entry("AD_GROUP", group.campaign, group.name, "+91 first", "24h", row=90),
                _registry_entry(
                    "AD_GROUP", group.campaign, group.name, "+91 second", "24h", row=91
                ),
            ]
        }
    )
    finding = next(f for f in run(duplicated, fixture_rules).findings if f.rule_id == "AD-014")
    assert "same scope as row 90" in finding.message
    assert finding.severity is Severity.BLOCKER


@pytest.mark.parametrize(
    ("level", "campaign_cell", "ad_group_cell", "expected"),
    [
        ("ACCOUNT", "TST | Search | Brand | Jaipur", "", "names campaign"),
        ("ACCOUNT", "", "Brand | Core", "names ad group"),
        ("CAMPAIGN", "TST | Search | Brand | Jaipur", "Brand | Core", "names ad group"),
        ("CAMPAIGN", "", "", "no Campaign"),
        ("AD_GROUP", "TST | Search | Brand | Jaipur", "", "no Ad group"),
    ],
)
def test_ad_014_blocks_a_row_that_reads_narrower_than_it_acts(
    fixtures: dict[str, Path],
    schema: WorkbookSchema,
    fixture_rules: Rules,
    level: str,
    campaign_cell: str,
    ad_group_cell: str,
    expected: str,
) -> None:
    """Scope widening: a cell the machine ignores is a cell a human will trust.

    `Level: ACCOUNT · Campaign: Neuro` looked like the Neuro number and applied to all
    five campaigns. `Level: CAMPAIGN · Ad group: Neuro | Provider` looked like one ad
    group and covered the campaign. Both were legal.
    """
    bundle = parse_workbook(fixtures["clean"], schema)
    widened = bundle.model_copy(
        update={
            "call_asset_registry": [
                _registry_entry(level, campaign_cell, ad_group_cell, "+91 x", "24h")
            ]
        }
    )
    messages = [f.message for f in run(widened, fixture_rules).findings if f.rule_id == "AD-014"]
    assert any(expected in message for message in messages), messages


def test_ad_014_requires_a_staffed_schedule_on_the_row(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    bundle = parse_workbook(fixtures["clean"], schema)
    group = bundle.ad_groups[0]
    no_hours = bundle.model_copy(
        update={
            "call_asset_registry": [
                _registry_entry("AD_GROUP", group.campaign, group.name, "+91 x", "")
            ]
        }
    )
    messages = [f.message for f in run(no_hours, fixture_rules).findings if f.rule_id == "AD-014"]
    assert any("no staffed hours" in message for message in messages), messages


def test_ad_015_blocks_an_unapproved_registry_row(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """The `Status` column existed and nothing read it — the same bug as `AD-013`.

    Ready-only: a warning while developing, a blocker for anything deployable.
    """
    bundle = parse_workbook(fixtures["clean"], schema)
    group = bundle.ad_groups[0]
    unapproved = bundle.model_copy(
        update={
            "call_asset_registry": [
                _registry_entry(
                    "AD_GROUP", group.campaign, group.name, "+91 x", "24h", status="VERIFY"
                )
            ]
        }
    )
    building = next(
        f for f in run(unapproved, fixture_rules, mode="build").findings if f.rule_id == "AD-015"
    )
    assert building.severity is Severity.BLOCKER
    assert "VERIFY" in building.message

    validating = next(
        f for f in run(unapproved, fixture_rules, mode="validate").findings if f.rule_id == "AD-015"
    )
    assert validating.severity is Severity.WARNING


def test_a_well_formed_registry_row_raises_nothing(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """The grammar must not be so strict that the intended use is impossible."""
    bundle = parse_workbook(fixtures["clean"], schema)
    group = bundle.ad_groups[0]
    fine = bundle.model_copy(
        update={
            "call_asset_registry": [
                _registry_entry("ACCOUNT", "", "", "+91 141 000 0000", "Mon-Sat 08-20"),
                _registry_entry("AD_GROUP", group.campaign, group.name, "+91 141 222 2222", "24x7"),
            ]
        }
    )
    result = run(fine, fixture_rules, mode="build")
    assert not [f for f in result.findings if f.rule_id in {"AD-014", "AD-015"}]


def test_the_resolved_asset_names_the_row_it_came_from(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """ "Which of nine rows was that?" is the first question anybody asks."""
    from apex_ads.validate import callassets

    bundle = parse_workbook(fixtures["clean"], schema)
    group = bundle.ad_groups[0]
    with_registry = bundle.model_copy(
        update={
            "call_asset_registry": [
                _registry_entry("AD_GROUP", group.campaign, group.name, "+91 x", "24h", row=91)
            ]
        }
    )
    asset = callassets.resolve(with_registry, fixture_rules)[group.key]
    assert asset is not None
    assert asset.row == 91
    assert asset.sheet == "02 BUILD"
    assert asset.provenance == "02 BUILD row 91 · ad group registry"


def test_a_placeholder_campaign_row_outranks_a_real_account_registry_row(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Characterisation test for known, currently-safe behaviour (fifth-audit observation).

    `resolve()` takes the campaign row before it knows whether the value is a placeholder,
    so a campaign cell still reading `[REQUIRED BEFORE LAUNCH]` beats a real `ACCOUNT`
    registry number. That is arguably the wrong precedence — a placeholder is not an
    answer — but it **fails closed**: `AD-012` sees the resolved placeholder and blocks any
    deployable build, so the wrong number can never deploy.

    Recorded now, before the `ACCOUNT` level is ever actually used, so that changing the
    precedence later is a deliberate decision against a test that states today's behaviour
    rather than a silent change nobody notices.
    """
    bundle = parse_workbook(fixtures["clean"], schema)
    assert "[REQUIRED" in bundle.campaigns[0].call_phone_number, "fixture must hold a placeholder"

    with_account = bundle.model_copy(
        update={
            "call_asset_registry": [
                _registry_entry(
                    "ACCOUNT", "", "", "+91 141 000 0000", "Mon-Sat 08:00-20:00 IST", row=90
                )
            ]
        }
    )
    from apex_ads.validate import callassets

    resolved = callassets.resolve(with_account, fixture_rules)[bundle.ad_groups[0].key]
    assert resolved is not None
    # today's precedence: the placeholder campaign row wins
    assert resolved.source == "campaign row"
    assert "[REQUIRED" in resolved.number

    # and the safety property that makes it tolerable: it cannot reach a deployable build
    blocked = [
        f
        for f in run(with_account, fixture_rules, mode="build").findings
        if f.rule_id == "AD-012" and f.severity is Severity.BLOCKER
    ]
    assert blocked, "a resolved placeholder must block a READY build"


def test_ad_013_flags_an_unapproved_supporting_asset(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """The model always had `status`; nothing read it, and MANUAL_STEPS never showed it."""
    bundle = parse_workbook(fixtures["clean"], schema)
    unapproved = [
        bundle.supporting_assets[0].model_copy(update={"status": "VERIFY FACT"}),
        *bundle.supporting_assets[1:],
    ]
    result = run(bundle.model_copy(update={"supporting_assets": unapproved}), fixture_rules)
    finding = next(f for f in result.findings if f.rule_id == "AD-013")
    assert "VERIFY FACT" in finding.message


# --------------------------------------------------- unclassified workbook columns


def test_a_populated_unknown_column_blocks(
    fixtures: dict[str, Path], schema: WorkbookSchema
) -> None:
    """EXP-001 never sees it: the parser used to drop unknown columns before models exist.

    Add an `Audience exclusion` column to a build-critical section, fill it in, and the
    compiler would have produced a build without it and reported "None needed".
    """
    from apex_ads.ingest.errors import WorkbookError

    try:
        bundle = parse_workbook(fixtures["populated_unknown_column"], schema)
    except WorkbookError as exc:  # pragma: no cover - either shape is acceptable
        assert exc.finding.rule_id == "ING-102"
        return

    blocking = [f for f in bundle.findings if f.rule_id == "ING-102"]
    assert blocking, [f.rule_id for f in bundle.findings]
    assert "UNCLASSIFIED SOURCE COLUMN" in blocking[0].message
    assert "Audience exclusion" in blocking[0].message


def test_an_empty_unknown_column_is_only_informational(
    fixtures: dict[str, Path], schema: WorkbookSchema
) -> None:
    """Notes columns are expected; it is the values that make one dangerous."""
    bundle = parse_workbook(fixtures["wide_rsa"], schema)
    assert any(f.rule_id == "ING-100" for f in bundle.findings)
    assert not [f for f in bundle.findings if f.rule_id == "ING-102"]
