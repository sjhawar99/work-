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
