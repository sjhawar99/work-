"""CLI tests run the real process, so exit codes are tested rather than mocked."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from apex_ads.exit_codes import ExitCode


def run(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo_root / "src" / "cli.py"), *args],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )


def test_version_succeeds_and_reports_provenance(repo_root: Path) -> None:
    result = run(repo_root, "version")
    assert result.returncode == ExitCode.OK
    assert "apex 0.1.0" in result.stdout
    assert "git commit" in result.stdout
    for name in ("rules", "workbook_schema", "editor_schema"):
        assert name in result.stdout


@pytest.mark.parametrize("command", ["drift"])
def test_unimplemented_commands_exit_bad_invocation(repo_root: Path, command: str) -> None:
    """`watchdog` left this list in Phase 6; `drift` is Phase 7 and still an honest stub."""
    result = run(repo_root, command)
    assert result.returncode == ExitCode.BAD_INVOCATION
    assert "not implemented" in result.stderr


def test_unknown_command_exits_five_not_two(repo_root: Path) -> None:
    """argparse defaults to 2, which this tool reserves for a validation BLOCKER."""
    result = run(repo_root, "frobnicate")
    assert result.returncode == ExitCode.BAD_INVOCATION


def test_no_subcommand_exits_five(repo_root: Path) -> None:
    assert run(repo_root).returncode == ExitCode.BAD_INVOCATION


def test_missing_config_directory_exits_five(repo_root: Path) -> None:
    result = run(repo_root, "version", "--config", "config-that-does-not-exist")
    assert result.returncode == ExitCode.BAD_INVOCATION
    assert "rules.yaml" in result.stderr


def test_help_exits_zero(repo_root: Path) -> None:
    result = run(repo_root, "--help")
    assert result.returncode == ExitCode.OK


def test_no_bypass_flags_anywhere_in_the_cli_surface(repo_root: Path) -> None:
    """Acceptance test 24 (spec §19.2): no --force, --skip-validation, --ignore-blockers."""
    surface = run(repo_root, "--help").stdout
    for command in ("build", "validate", "watchdog", "drift", "version"):
        surface += run(repo_root, command, "--help").stdout
    for flag in ("--force", "--skip-validation", "--ignore-blockers", "--yes"):
        assert flag not in surface, flag


# ------------------------------------------------------------------- apex validate


def run_validate(repo_root: Path, workbook: Path, out: Path, *extra: str):
    """Run `apex validate` without touching the network.

    `--no-network` is the default here on purpose. These tests exercise the CLI — exit
    codes, report contents, which files appear — not reachability. Without it they fetch
    real Apex URLs, which makes them slow where the network is fast and hanging where it
    is not, and makes "the suite passes" a statement about somebody's connection.

    Actual URL-check behaviour is covered by `tests/unit/test_urlcheck.py`, where the
    fetcher is injected and every outcome is deterministic.
    """
    return run(
        repo_root,
        "validate",
        "--workbook",
        str(workbook),
        "--out",
        str(out),
        "--no-network",
        *extra,
    )


def test_validate_reports_a_blocker_and_exits_two(
    repo_root: Path, fixtures: dict[str, Path], tmp_path: Path
) -> None:
    result = run_validate(repo_root, fixtures["open_red_action"], tmp_path)
    assert result.returncode == ExitCode.BLOCKER
    assert "RESULT: VALIDATION FAILED" in result.stdout
    assert "[ACT-001]" in result.stdout
    assert "NO DEPLOYABLE FILES GENERATED" in result.stdout


def test_validate_never_writes_editor_csvs(
    repo_root: Path, fixtures: dict[str, Path], tmp_path: Path
) -> None:
    """`apex validate` validates. It has no path that emits an importable file."""
    run_validate(repo_root, fixtures["clean"], tmp_path)
    written = {path.name for path in tmp_path.rglob("*") if path.is_file()}
    assert written == {"PRE_FLIGHT_REPORT.txt", "findings.json"}


def test_validate_missing_column_names_sheet_and_column(
    repo_root: Path, fixtures: dict[str, Path], tmp_path: Path
) -> None:
    """Acceptance test 8 (spec §19.2): a structural failure is a reported BLOCKER."""
    result = run_validate(repo_root, fixtures["renamed_column"], tmp_path)
    assert result.returncode == ExitCode.BLOCKER
    assert "[ING-003]" in result.stdout
    assert "02 BUILD" in result.stdout
    assert "Monthly budget" in result.stdout


def test_validate_missing_workbook_exits_five(repo_root: Path, tmp_path: Path) -> None:
    result = run_validate(repo_root, tmp_path / "absent.xlsx", tmp_path)
    assert result.returncode == ExitCode.BAD_INVOCATION
    assert "not found" in result.stderr


# ---------------------------------------------------------------------- apex build


def test_build_on_a_blocked_workbook_writes_no_importable_files(
    repo_root: Path, fixtures: dict[str, Path], tmp_path: Path
) -> None:
    """The real workbook is in this state today: blockers, so nothing importable."""
    result = run(
        repo_root,
        "build",
        "--workbook",
        str(fixtures["open_red_action"]),
        "--out",
        str(tmp_path),
        "--no-network",
    )
    assert result.returncode == ExitCode.BLOCKER
    assert "BUILD FAILED" in result.stderr
    assert not list(tmp_path.rglob("*.csv"))
    assert not list(tmp_path.glob("*.partial"))


def test_build_without_network_is_never_deployable(
    repo_root: Path, fixtures: dict[str, Path], tmp_path: Path
) -> None:
    """Even with no blockers, unverified destinations cannot yield an importable build."""
    result = run(
        repo_root,
        "build",
        "--workbook",
        str(fixtures["clean"]),
        "--out",
        str(tmp_path),
        "--no-network",
    )
    assert result.returncode in {ExitCode.BLOCKER, ExitCode.DRAFT}
    assert "BUILD READY" not in result.stderr
    assert not (tmp_path / "latest").exists()


def test_a_misrouted_record_type_exits_two_and_says_so_in_the_report(
    repo_root: Path, fixtures: dict[str, Path], fixture_config_dir: Path, tmp_path: Path
) -> None:
    """`EXP-002` has to reach the document a human reads.

    Route `ads` to `editor`, where no writer exists, and the build fails. Before the
    findings were merged, the process exited 2 while `PRE_FLIGHT_REPORT.txt` listed no
    blocker at all — because `EXP-001`/`EXP-002` are discovered inside the build, after
    validation has already produced its result. "FAILED, and nothing is wrong" is the
    single most corrosive thing a report can say.
    """
    import yaml

    schema_path = fixture_config_dir / "editor_schema.yaml"
    original = schema_path.read_text(encoding="utf-8")
    schema = yaml.safe_load(original)
    schema["inventory"]["ads"] = "editor"
    schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8")
    try:
        result = run(
            repo_root,
            "build",
            "--workbook",
            str(fixtures["real_call_number"]),
            "--out",
            str(tmp_path),
            "--no-network",
            "--config",
            str(fixture_config_dir),
        )
    finally:
        schema_path.write_text(original, encoding="utf-8")

    assert result.returncode == ExitCode.BLOCKER
    assert "BUILD FAILED" in result.stderr
    assert "[EXP-002]" in result.stdout
    assert "no Editor writer exists" in result.stdout
    assert not list(tmp_path.rglob("*.csv"))


def test_a_build_report_lists_the_compile_stage_findings(
    repo_root: Path, fixtures: dict[str, Path], fixture_config_dir: Path, tmp_path: Path
) -> None:
    """The merge is not only for failures: `CMP-101` is an INFO found at compile time.

    The fixture's monthly budget is right and its daily cell is wrong. The build exports
    the derived daily figure and records that it did — and that record now reaches the
    report, where somebody can see the spreadsheet and the build disagree.
    """
    result = run(
        repo_root,
        "build",
        "--workbook",
        str(fixtures["wrong_daily_budget"]),
        "--out",
        str(tmp_path),
        "--no-network",
        "--config",
        str(fixture_config_dir),
    )
    assert result.returncode == ExitCode.DRAFT
    assert "[CMP-101]" in result.stdout


def test_build_never_uploads_anything(repo_root: Path) -> None:
    """Guardrail §18.1: the build surface offers no way to reach Google Ads."""
    surface = run(repo_root, "build", "--help").stdout
    for flag in ("--upload", "--push", "--post", "--enable", "--live"):
        assert flag not in surface, flag


# -------------------------------------------------------------------- apex watchdog


def test_watchdog_runs_and_reports(
    repo_root: Path,
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    fixture_config_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole chain through the real process, including exit code."""
    monkeypatch.setenv("APEX_QUERY_ID_KEY", "ab" * 32)
    result = run(
        repo_root,
        "watchdog",
        "--workbook",
        str(fixtures["clean"]),
        "--search-terms",
        str(exports["clean"].parent),
        "--out",
        str(tmp_path),
        "--config",
        str(fixture_config_dir),
    )
    assert result.returncode == ExitCode.OK, result.stderr
    assert "SEARCH-TERM WATCHDOG" in result.stdout
    assert "WATCHDOG COMPLETE" in result.stderr
    assert "were not modified" in result.stderr

    directories = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert len(directories) == 1
    assert (directories[0] / "search_term_analysis.csv").is_file()


def test_watchdog_exits_two_when_the_export_cannot_be_read(
    repo_root: Path,
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    fixture_config_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed: no partial analysis, and the reason on stderr."""
    monkeypatch.setenv("APEX_QUERY_ID_KEY", "ab" * 32)
    result = run(
        repo_root,
        "watchdog",
        "--workbook",
        str(fixtures["clean"]),
        "--search-terms",
        str(exports["missing_column"]),
        "--out",
        str(tmp_path),
        "--config",
        str(fixture_config_dir),
    )
    assert result.returncode == ExitCode.BLOCKER
    assert "[WD-001]" in result.stderr
    assert not list(tmp_path.rglob("*.csv"))


def test_watchdog_never_prints_a_raw_query_to_the_terminal(
    repo_root: Path,
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    fixture_config_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Console output is named in the privacy rule alongside logs and findings.json."""
    monkeypatch.setenv("APEX_QUERY_ID_KEY", "ab" * 32)
    result = run(
        repo_root,
        "watchdog",
        "--workbook",
        str(fixtures["clean"]),
        "--search-terms",
        str(exports["clean"].parent),
        "--out",
        str(tmp_path),
        "--config",
        str(fixture_config_dir),
    )
    combined = result.stdout + result.stderr
    for query in (
        "paralysis treatment cost jaipur",
        "apex hospital booking",
        "zzz unknown phrase here",
    ):
        assert query not in combined


def test_watchdog_offers_no_way_to_reach_google_ads(repo_root: Path) -> None:
    """Guardrail §18.1, restated for the new subcommand surface."""
    surface = run(repo_root, "watchdog", "--help").stdout
    for flag in ("--upload", "--push", "--apply", "--post", "--enable", "--live", "--force"):
        assert flag not in surface
    assert "--propose-writeback" in surface
