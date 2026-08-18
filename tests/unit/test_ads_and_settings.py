"""Phase 4 rules: ad copy, call assets, landing pages, tracking and settings hygiene."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex_ads.ingest.urlcheck import UrlResult
from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import Rules, WorkbookSchema
from apex_ads.models.findings import Severity
from apex_ads.validate.registry import validators_for
from apex_ads.validate.runner import ValidationResult, run


def validate(
    path: Path,
    schema: WorkbookSchema,
    rules: Rules,
    *,
    url_results: dict[str, UrlResult] | None = None,
    mode: str = "validate",
) -> ValidationResult:
    bundle = parse_workbook(path, schema)
    return run(bundle, rules, validators=validators_for(url_results), mode=mode)  # type: ignore[arg-type]


def ids_of(result: ValidationResult, severity: Severity | None = None) -> set[str]:
    findings = (
        result.findings
        if severity is None
        else [f for f in result.findings if f.severity is severity]
    )
    return {finding.rule_id for finding in findings}


@pytest.fixture(scope="module")
def clean(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> ValidationResult:
    return validate(fixtures["clean"], schema, fixture_rules)


# --------------------------------------------------------------------------- ads


def test_ad_002_catches_an_over_long_headline(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 10."""
    result = validate(fixtures["long_headline"], schema, fixture_rules)
    finding = next(f for f in result.blockers if f.rule_id == "AD-002")
    assert "H1" in finding.message
    assert "44 characters" in finding.message
    assert "Shorten it by 14" in finding.remedy


def test_ad_rules_are_quiet_on_clean_copy(clean: ValidationResult) -> None:
    for rule_id in ("AD-001", "AD-002", "AD-003", "AD-004", "AD-005", "AD-007", "AD-009", "AD-011"):
        assert rule_id not in ids_of(clean), rule_id


def test_ad_006_requires_a_resolution_not_nine_entries(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """One campaign-level number covers every ad group beneath it (Decision A5)."""
    result = validate(fixtures["real_call_number"], schema, fixture_rules)
    assert "AD-006" not in ids_of(result)


def test_ad_006_blocks_when_nothing_resolves(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    bundle = parse_workbook(fixtures["clean"], schema)
    stripped = [c.model_copy(update={"call_phone_number": ""}) for c in bundle.campaigns]
    result = run(bundle.model_copy(update={"campaigns": stripped}), fixture_rules)
    assert "AD-006" in ids_of(result, Severity.BLOCKER)


def test_ad_012_is_a_warning_when_validating(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 37: development continues with a placeholder number."""
    result = validate(fixtures["clean"], schema, fixture_rules, mode="validate")
    finding = next(f for f in result.warnings if f.rule_id == "AD-012")
    assert "blocks a deployable build" in finding.message
    assert "AD-012" not in ids_of(result, Severity.BLOCKER)


def test_ad_012_blocks_a_deployable_build(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 38: a READY build stays impossible until the number is real."""
    result = validate(fixtures["clean"], schema, fixture_rules, mode="build")
    assert "AD-012" in ids_of(result, Severity.BLOCKER)


def test_ad_012_is_satisfied_by_a_real_number(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    result = validate(fixtures["real_call_number"], schema, fixture_rules, mode="build")
    assert "AD-012" not in ids_of(result)


# ----------------------------------------------------------------- landing pages


def _results(*, status: str, reason: str = "", http: int | None = None) -> dict[str, UrlResult]:
    paths = [
        "/google/apex-jaipur",
        "/google/book-apex-jaipur",
        "/google/neurologist-jaipur",
    ]
    return {
        path: UrlResult(
            url=f"https://www.apexhospitals.com{path}",
            status=status,  # type: ignore[arg-type]
            reason=reason or status.lower(),
            http_status=http,
        )
        for path in paths
    }


def test_lp_003_blocks_an_unreachable_page(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 31."""
    result = validate(
        fixtures["clean"],
        schema,
        fixture_rules,
        url_results=_results(status="BLOCKER", reason="returned 404", http=404),
    )
    finding = next(f for f in result.blockers if f.rule_id == "LP-003")
    assert "404" in finding.message


def test_lp_003_treats_unknown_as_a_warning_never_a_pass(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 33: UNKNOWN is surfaced, and never counted as verified."""
    result = validate(
        fixtures["clean"],
        schema,
        fixture_rules,
        url_results=_results(status="UNKNOWN", reason="network validation could not complete"),
    )
    finding = next(f for f in result.warnings if f.rule_id == "LP-003")
    assert "UNKNOWN" in finding.message
    assert "not a pass" in finding.remedy


def test_lp_003_says_so_when_it_did_not_run(clean: ValidationResult) -> None:
    finding = next(f for f in clean.warnings if f.rule_id == "LP-003")
    assert "was not checked" in finding.message


def test_lp_003_is_quiet_when_every_page_passes(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    result = validate(
        fixtures["clean"],
        schema,
        fixture_rules,
        url_results=_results(status="PASS", http=200),
    )
    assert "LP-003" not in ids_of(result)


def test_lp_004_reports_an_off_domain_redirect(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 32."""
    result = validate(
        fixtures["clean"],
        schema,
        fixture_rules,
        url_results=_results(
            status="BLOCKER", reason="redirected off-domain to https://elsewhere.example/x"
        ),
    )
    finding = next(f for f in result.blockers if f.rule_id == "LP-004")
    assert "elsewhere.example" in finding.message


def test_lp_002_requires_the_two_sheets_to_agree(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    bundle = parse_workbook(fixtures["clean"], schema)
    moved = [
        bundle.ad_groups[0].model_copy(update={"planned_landing_page": "/google/elsewhere"}),
        *bundle.ad_groups[1:],
    ]
    result = run(bundle.model_copy(update={"ad_groups": moved}), fixture_rules)
    finding = next(f for f in result.blockers if f.rule_id == "LP-002")
    assert "/google/elsewhere" in finding.message


# ---------------------------------------------------------------------- tracking


def test_tracking_rules_pass_on_a_complete_measurement_contract(clean: ValidationResult) -> None:
    for rule_id in ("TRK-001", "TRK-002", "TRK-003", "TRK-004", "TRK-007"):
        assert rule_id not in ids_of(clean, Severity.BLOCKER), rule_id


def test_trk_003_blocks_when_auto_tagging_is_not_declared(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    bundle = parse_workbook(fixtures["clean"], schema)
    without = [item for item in bundle.measurement_contract if "Click identity" not in item.item]
    result = run(bundle.model_copy(update={"measurement_contract": without}), fixture_rules)
    assert "TRK-003" in ids_of(result, Severity.BLOCKER)
    assert "TRK-004" in ids_of(result, Severity.BLOCKER)


def test_trk_006_is_silent_when_no_tracking_template_exists(clean: ValidationResult) -> None:
    """Acceptance test 42 — a valid campaign is never blocked for lacking one."""
    assert "TRK-006" not in ids_of(clean, Severity.BLOCKER)
    finding = next(f for f in clean.infos if f.rule_id == "TRK-006")
    assert "not applicable" in finding.message


def test_trk_005_keeps_utms_advisory(clean: ValidationResult) -> None:
    finding = next(f for f in clean.infos if f.rule_id == "TRK-005")
    assert "recommended, not required" in finding.message


# ---------------------------------------------------------------------- settings


def test_set_001_blocks_search_partners(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    result = validate(fixtures["search_partners_on"], schema, fixture_rules)
    finding = next(f for f in result.blockers if f.rule_id == "SET-001")
    assert "Partners" in finding.message


def test_settings_pass_on_a_correct_campaign(clean: ValidationResult) -> None:
    for rule_id in ("SET-001", "SET-002", "SET-003", "SET-004"):
        assert rule_id not in ids_of(clean), rule_id
