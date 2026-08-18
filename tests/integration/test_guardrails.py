"""Guardrail enforcement tests (spec §18, §19.2 tests 24-25).

These matter as much as the functional tests: they fail if a future change quietly
weakens a safety rail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SOURCE_GLOB = "src/**/*.py"

FORBIDDEN_IMPORTS = (
    r"\bfrom\s+google\.ads",
    r"\bimport\s+google\.ads",
    r"\bgoogle-ads\b",
    r"\bfrom\s+google\.oauth2",
    r"\bimport\s+google_auth",
)

FORBIDDEN_FLAGS = ("--force", "--skip-validation", "--ignore-blockers", "--no-validate")


def source_files(repo_root: Path) -> list[Path]:
    return sorted(repo_root.glob(SOURCE_GLOB))


def test_source_tree_is_not_empty(repo_root: Path) -> None:
    assert source_files(repo_root)


@pytest.mark.parametrize("pattern", FORBIDDEN_IMPORTS)
def test_no_google_ads_api_client_is_imported(repo_root: Path, pattern: str) -> None:
    """Acceptance test 25: v1 deploys through Editor, by a human. No API, ever."""
    for path in source_files(repo_root):
        assert not re.search(pattern, path.read_text(encoding="utf-8")), f"{path}: {pattern}"


@pytest.mark.parametrize("flag", FORBIDDEN_FLAGS)
def test_no_bypass_flag_is_defined(repo_root: Path, flag: str) -> None:
    """Acceptance test 24: a BLOCKER is fixed in the workbook, never bypassed.

    Checks argument *definitions*, not mentions — prose explaining why a bypass flag is
    forbidden is welcome; an `add_argument` call creating one is not.
    """
    definition = re.compile(rf"""add_argument\(\s*["']{re.escape(flag)}["']""")
    for path in source_files(repo_root):
        assert not definition.search(path.read_text(encoding="utf-8")), f"{path}: {flag}"


def test_exit_codes_match_the_specified_contract(repo_root: Path) -> None:
    from apex_ads.exit_codes import ExitCode

    assert (ExitCode.OK, ExitCode.BLOCKER, ExitCode.ERROR) == (0, 2, 3)
    assert (ExitCode.DRIFT, ExitCode.BAD_INVOCATION, ExitCode.DRAFT) == (4, 5, 6)


def test_no_source_file_writes_to_the_input_directory(repo_root: Path) -> None:
    """The workbook export is read-only; the Google Sheet is the source of truth."""
    writes = re.compile(r"""open\(\s*["'][^"']*input/[^"']*["']\s*,\s*["'][wa]""")
    for path in source_files(repo_root):
        assert not writes.search(path.read_text(encoding="utf-8")), path
