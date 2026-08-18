"""The pre-flight report (spec §12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import Rules, WorkbookSchema
from apex_ads.report import preflight
from apex_ads.validate.runner import run


@pytest.fixture(scope="module")
def rendered(fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules) -> str:
    bundle = parse_workbook(fixtures["budget_mismatch"], schema)
    result = run(bundle, fixture_rules)
    return preflight.render(
        bundle, result, run_id="20260818-120000-abcd1234", config_hashes={"rules": "f" * 64}
    )


def test_header_carries_provenance(rendered: str) -> None:
    assert "APEX GOOGLE ADS OS — PRE-FLIGHT REPORT" in rendered
    assert "20260818-120000-abcd1234" in rendered
    assert "sha256" in rendered


def test_export_age_is_not_claimed_as_freshness(rendered: str) -> None:
    """WB-001 is advisory: file age is never reported as agreement with the Sheet."""
    assert "not proof it matches the Google Sheet" in rendered


def test_url_checks_are_reported_as_not_run(rendered: str) -> None:
    """A check that has not been built must never read as a check that passed."""
    assert "URL checks: NOT RUN" in rendered


def test_failure_headline_and_footer(rendered: str) -> None:
    assert "RESULT: VALIDATION FAILED" in rendered
    assert "NO DEPLOYABLE FILES GENERATED" in rendered


def test_blockers_carry_coordinates_and_remedies(rendered: str) -> None:
    assert "[BUD-001]" in rendered
    assert "Fix:" in rendered


def test_summary_marks_the_failing_line(rendered: str) -> None:
    assert "❌ Monthly budget" in rendered
    assert "✅ Campaigns" in rendered


def test_lines_stay_readable(rendered: str) -> None:
    """The report is meant to be read in a terminal or pasted into a chat."""
    overlong = [line for line in rendered.splitlines() if len(line) > 110]
    assert not overlong, overlong[:2]


def test_long_messages_wrap_under_a_hanging_indent(fixtures, schema, fixture_rules) -> None:
    from apex_ads.ingest.workbook import parse_workbook
    from apex_ads.report import preflight
    from apex_ads.validate.runner import run

    bundle = parse_workbook(fixtures["clean"], schema)
    text = preflight.render(
        bundle, run(bundle, fixture_rules), run_id="run", config_hashes={"rules": "a" * 64}
    )
    assert "[AD-012]" in text
    assert all(len(line) <= 110 for line in text.splitlines())


def test_passing_report_says_so(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    bundle = parse_workbook(fixtures["clean"], schema)
    text = preflight.render(
        bundle, run(bundle, fixture_rules), run_id="run", config_hashes={"rules": "a" * 64}
    )
    assert "RESULT: VALIDATION PASSED" in text
    assert "NO DEPLOYABLE FILES GENERATED" not in text


def test_write_produces_report_and_machine_readable_findings(
    tmp_path: Path, fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    bundle = parse_workbook(fixtures["open_red_action"], schema)
    result = run(bundle, fixture_rules)
    report = preflight.write(
        tmp_path, bundle, result, run_id="run-1", config_hashes={"rules": "b" * 64}
    )

    assert report.is_file()
    payload = json.loads((tmp_path / "findings.json").read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["counts"]["BLOCKER"] >= 1
    assert payload["workbook"]["sha256"] == bundle.source_sha256
    assert any(finding["rule_id"] == "ACT-001" for finding in payload["findings"])


def test_reports_are_redacted(
    tmp_path: Path, fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Privacy applies to every generated artifact, not only to logs (Decision C7)."""
    bundle = parse_workbook(fixtures["clean"], schema)
    action = bundle.blocking_actions[0].model_copy(
        update={"severity": "RED", "status": "Open", "task": "call 9876543210 to confirm"}
    )
    mutated = bundle.model_copy(update={"blocking_actions": [action]})
    result = run(mutated, fixture_rules)
    preflight.write(tmp_path, mutated, result, run_id="run-2", config_hashes={"rules": "c" * 64})

    report_text = (tmp_path / "PRE_FLIGHT_REPORT.txt").read_text(encoding="utf-8")
    findings_text = (tmp_path / "findings.json").read_text(encoding="utf-8")
    assert "9876543210" not in report_text
    assert "9876543210" not in findings_text
    assert "[phone]" in report_text
