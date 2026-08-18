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


@pytest.mark.parametrize("command", ["build", "watchdog", "drift"])
def test_unimplemented_commands_exit_bad_invocation(repo_root: Path, command: str) -> None:
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
    return run(
        repo_root,
        "validate",
        "--workbook",
        str(workbook),
        "--out",
        str(out),
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
