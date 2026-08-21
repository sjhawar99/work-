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
    assert "INTENTIONAL_NON_REACH" in module
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


def test_the_normative_documents_agree_with_the_no_authoring_decision(repo_root: Path) -> None:
    """A spec clause is an instruction to whoever implements next.

    Four rounds of audit went into removing negative authoring from the code while the
    canonical spec still said the Watchdog "suggests" and a human "approves", and while the
    task list carried an unticked ingest module under a path that was never built. AGENTS.md
    tells a coding agent to trust these files. Left as they were, they read as a to-do list
    for rebuilding exactly what was removed — this project's own governance instructing the
    next robot to reintroduce the defect.

    Prose, so asserted narrowly: the abandoned model must not appear as a live instruction,
    and Phase 6 must not still be asking for a module that exists.
    """
    spec = (repo_root / "docs" / "CODEX_BUILD_SPEC.md").read_text(encoding="utf-8")
    tasks = (repo_root / "CODEX_TASKS.md").read_text(encoding="utf-8")

    assert "Author negative policy at all (Stage 1)" in spec

    assert "- [ ] `ingest/search_terms.py`" not in tasks
    phase_six = tasks.split("## Phase 6")[1].split("## Phase 7")[0]
    assert "- [ ] " not in phase_six, "Phase 6 is complete; an open box is a build instruction"

    live = _live_spec(spec)

    # The §13 contract, which is what a reader of the section acts on.
    assert "negative-policy observations" in live
    assert "suggested negatives" not in live

    # Acceptance criteria define what "done" means. These two required the abandoned
    # architecture outright — the code stopped resurrecting it four audits ago while the
    # tests kept asking for it back.
    assert "Suggestions produced, each with evidence" not in live
    assert "INTENTIONAL_NON_REACH" in live
    assert "OBSERVED_DESPITE_NEGATIVE" in live

    # Anywhere in the live spec that still uses the abandoned architecture's vocabulary must
    # be saying it is gone. A line may name it to remove it; it may not name it to require it.
    for number, line in enumerate(live.splitlines(), 1):
        if not _ABANDONED.search(line):
            continue
        assert _REMOVAL.search(line), f"live spec line {number} requires the removed model: {line}"

    # And the Watchdog's acceptance criteria are **pinned**, because a word list cannot stop a
    # paraphrase. "Watchdog offers candidate exclusions — each candidate emitted with its
    # evidence" reintroduces the whole architecture without using a single banned word, and a
    # vocabulary rule waves it through. These rows define what "done" means for Phase 6; if
    # one of them is genuinely meant to change, the change belongs here too, deliberately,
    # in the same commit.
    # The writeback contract, which the pinned rows above do not cover: §13.7 went on
    # describing appendable keyword blocks, for two sheets that have never existed, while
    # §13.5, the acceptance tests and the code all said otherwise.
    writeback = live.split("### 13.7")[1].split("## 14.")[0]
    assert "01_ACTIONS_append.csv" in writeback
    assert "HOW_TO_PASTE.txt" in writeback
    # Only the part before the amendment note. The note names the ghost sheets in order to
    # bury them, and it wraps across lines, so a line-by-line "is this a removal" test
    # cannot read it — the paragraph is the unit of meaning, not the line.
    contract = writeback.split("**AMENDED")[0]
    for ghost in _GHOST_SHEETS:
        assert ghost not in contract, f"{ghost} does not exist in the workbook (decision C1)"
    assert "no keyword file" in contract.lower()

    rows = {
        number: text
        for number, text in _acceptance_rows(live).items()
        if number in _WATCHDOG_ACCEPTANCE
    }
    assert rows == _WATCHDOG_ACCEPTANCE, (
        "Watchdog acceptance criteria changed. If that is intended, update "
        "_WATCHDOG_ACCEPTANCE in this test in the same commit — these rows silently "
        "described a removed architecture for four audit rounds."
    )


def _acceptance_rows(spec: str) -> dict[str, str]:
    """`{number: rest-of-row}` for every numbered row of the acceptance-test table."""
    rows: dict[str, str] = {}
    for line in spec.splitlines():
        match = re.match(r"^\|\s*(\d+)\s*\|(.*)\|\s*$", line)
        if match:
            rows[match.group(1)] = match.group(2).strip()
    return rows


_GHOST_SHEETS = ("06 NEGATIVE KEYWORDS", "09 SEARCH TERM MONITOR")
"""Sheets from the abandoned eleven-area design. The workbook has four (decision C1)."""


_WATCHDOG_ACCEPTANCE = {
    "18": "Watchdog leakage | `st_leakage.csv` produces `SPECIALTY_LEAK` rows with "
    "expected vs actual owner",
    "19": "Negative-policy reach | A matching approved negative **outside** its configured "
    "reach produces `INTENTIONAL_NON_REACH` only — INFO, no action row, and no "
    "`BRAND_LEAK` for the same event",
    "20": "No negative-policy authoring | The Watchdog emits no new negative text, no "
    "list-reach proposal and no `03_KEYWORDS_append.csv`. A negative whose reach **does** "
    "cover the campaign, served anyway, produces `OBSERVED_DESPITE_NEGATIVE`",
    "21": "Watchdog unresolved term | Labelled `CLASSIFIER_UNRESOLVED`, not force-fitted",
    "22": "Watchdog never writes the workbook | Workbook SHA-256 identical before and "
    "after every command",
}
"""Phase 6's acceptance criteria, held here so the spec cannot drift away from them alone."""


def _live_spec(spec: str) -> str:
    """The spec minus its `<details>` blocks.

    Superseded sections are preserved inside `<details>` on purpose — the reasoning is worth
    keeping and a reader can see what changed. Those are history. Everything outside them is
    a live instruction to whoever implements next, which is the only part this rule governs.
    """
    return re.sub(r"<details>.*?</details>", "", spec, flags=re.S)


_ABANDONED = re.compile(
    r"suggest\w*|ROUTING_CONFLICT|negatives_suggestions|03_KEYWORDS_append", re.IGNORECASE
)
"""Vocabulary that exists only in the negative-authoring architecture Stage 1 removed.

Deliberately excludes `propose`/`proposal`: `--propose-writeback` is a real, current flag,
and a rule that fires on the live CLI surface is a rule somebody switches off.
"""

_REMOVAL = re.compile(
    r"\bno\b|\bnot\b|\bnever\b|\bwithout\b|AMENDED|[Ss]uperseded|previously read|"
    r"no longer|removed|abandoned"
)
"""A marker that the line is describing the removal rather than requiring the thing."""
