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


def test_parsing_a_fixture_never_modifies_it(fixtures: dict[str, Path], schema: object) -> None:
    """No code path writes to a workbook, fixture or export alike."""
    from apex_ads.ingest.workbook import parse_workbook
    from apex_ads.util.hashing import sha256_file

    path = fixtures["clean"]
    before = sha256_file(path)
    parse_workbook(path, schema)  # type: ignore[arg-type]
    assert sha256_file(path) == before


def test_daily_sheet_cannot_reach_compilation(repo_root: Path) -> None:
    """04 DAILY is context only — nothing outside ingest may read `daily_log` yet."""
    consumers = [
        path
        for path in source_files(repo_root)
        if "daily_log" in path.read_text(encoding="utf-8")
        and path.name not in {"workbook.py", "config.py"}
    ]
    assert not consumers, consumers


# ------------------------------------------------- the five Phase-6 invariants


def test_no_threshold_default_is_invented_anywhere(repo_root: Path) -> None:
    """Invariant 3: `null` means rank-and-review, and one `or 0` would end that.

    Scans the Watchdog for the shapes that quietly turn "we do not know yet" into a
    number: `or 0`, `or Decimal(`, `if x is None: x = ...` against a threshold.
    """
    watchdog = sorted((repo_root / "src" / "apex_ads" / "watchdog").glob("*.py"))
    assert watchdog
    forbidden = re.compile(r"threshold[a-z_]*\s*(or|if\s+.*else)\s|\bor\s+(0|Decimal\(|1\b)")
    for path in watchdog:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            assert not forbidden.search(line), f"{path.name}:{number}: {line.strip()}"


def test_every_stage_one_threshold_ships_null(repo_root: Path) -> None:
    """Invariant 3, at the config rather than the code."""
    import yaml

    rules = yaml.safe_load((repo_root / "config" / "rules.yaml").read_text(encoding="utf-8"))
    thresholds = rules["watchdog"]["thresholds"]
    assert thresholds
    assert all(value is None for value in thresholds.values()), thresholds


def test_the_watchdog_cannot_write_outside_its_output_directory(repo_root: Path) -> None:
    """Invariant 5: the four-sheet source stays untouched.

    No module in the package may open the workbook, or anything under `input/`, for
    writing. `--propose-writeback` emits new files inside the run directory.
    """
    writes = re.compile(r"""open\([^)]*["']w|write_text\(|write_bytes\(|\.save\(""")
    inputs = re.compile(r"""input/|workbook\.xlsx""")
    for path in sorted((repo_root / "src" / "apex_ads" / "watchdog").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#") or not writes.search(line):
                continue
            assert not inputs.search(line), f"{path.name}:{number}: {line.strip()}"


def test_the_watchdog_never_authors_negative_policy(repo_root: Path) -> None:
    """Invariant 4, restated after the Stage-1 decision.

    The Watchdog observes; it does not propose negatives and does not propose changing
    which campaigns a shared list covers. `suggestions.py` is gone, and the writeback emits
    no keyword block — the previous version proposed adding Brand to `ROUTE_COMPETITORS`,
    which is a frozen policy decision, not an enforcement repair.
    """
    watchdog = repo_root / "src" / "apex_ads" / "watchdog"
    assert not (watchdog / "suggestions.py").exists()

    module = (watchdog / "observations.py").read_text(encoding="utf-8")
    assert "POLICY_SCOPE_REVIEW" in module
    assert "OBSERVED_DESPITE_NEGATIVE" in module
    for verb in ("def apply", "def commit", "auto_apply", "AUTO_APPLY", "class Candidate"):
        assert verb not in module, verb

    # Checked against the module's namespace, not its prose: the docstring names the file
    # it no longer writes, in order to explain why. A guardrail that fires on an
    # explanation is a guardrail somebody deletes.
    from apex_ads.watchdog import writeback

    names = set(vars(writeback))
    assert "KEYWORD_HEADERS" not in names
    assert "keyword_rows" not in names
    assert not [
        value
        for name, value in vars(writeback).items()
        if isinstance(value, str)
        and name.isupper()
        and value.endswith(".csv")
        and "KEYWORD" in value.upper()
    ]


def test_the_query_id_key_is_never_written_into_output(repo_root: Path) -> None:
    """Invariant 2: the secret is an operating dependency, not an artifact."""
    # The attribute itself, not the directory name: `.apex_secrets/` appears in remedy
    # text, and a guardrail that fires on prose is a guardrail somebody deletes.
    access = re.compile(r"(?<!apex)\b_secret\b")
    for path in sorted((repo_root / "src" / "apex_ads").rglob("*.py")):
        if not access.search(path.read_text(encoding="utf-8")):
            continue
        assert path.name == "queryid.py", f"{path} reaches the raw secret"
