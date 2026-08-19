"""Watchdog outputs, privacy and writeback (spec §13.6-§13.7).

The privacy tests here are the ones that matter most: `search_term_analysis.csv` is
deliberately allowed to carry the words, and **every other output must not**. A test that
only checked "no query anywhere" would fail on the file that is supposed to have them, so
each file is checked against what it is actually permitted to contain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import Config, WorkbookSchema
from apex_ads.util.queryid import QueryIdKey
from apex_ads.watchdog.run import execute

CARRIES_WORDS = {"search_term_analysis.csv"}
"""**Exactly one** artifact may contain raw search terms.

This constant previously named two files, one line under a docstring saying every other
output must not contain the words — the test codifying the contradiction it was written to
catch. `routing_issues.csv` also carried a `search_term` column, so the operating contract
the plain-English guide gave the operator ("only search_term_analysis.csv has the actual
searches") was false, and the surface somebody could forward by accident was double what
they were told.

The test below now asserts the count, not a membership list: any future file that starts
revealing queries fails it without anybody remembering to update a set.
"""


@pytest.fixture()
def run(
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    schema: WorkbookSchema,
    watchdog_config: Config,
    query_key: QueryIdKey,
    tmp_path: Path,
):
    bundle = parse_workbook(fixtures["clean"], schema)
    return execute(
        bundle,
        watchdog_config,
        query_key,
        search_terms=exports["clean"].parent,
        out_root=tmp_path,
        run_id="wd-20260818-000000",
        propose_writeback=True,
        write_dashboard=True,
    )


def test_every_specified_file_is_written(run) -> None:
    names = {path.name for path in run.directory.iterdir()}
    assert {
        "search_term_analysis.csv",
        "negatives_suggestions.csv",
        "routing_issues.csv",
        "actions_report.txt",
        "parse_errors.csv",
        "dashboard.html",
        "manifest.json",
    } <= names


def test_parse_errors_is_written_even_when_empty(run) -> None:
    """Absence of the file would look like absence of the check."""
    path = run.directory / "parse_errors.csv"
    assert path.is_file()
    assert path.read_text(encoding="utf-8").startswith("source_file,row,query_id")


def test_exactly_one_artifact_contains_raw_search_terms(run) -> None:
    """The contract, asserted as a count over everything the run produced.

    Written this way deliberately. A membership list is a place to add an exception; a
    count is a thing that breaks when somebody does.
    """
    queries = [item.row.term.reveal() for item in run.analysed]
    assert queries

    revealing = set()
    for path in sorted(run.directory.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(query in text for query in queries):
            revealing.add(path.relative_to(run.directory).as_posix())

    assert revealing == CARRIES_WORDS, (
        f"exactly one artifact may hold raw queries; these do: {sorted(revealing)}"
    )


def test_routing_issues_identifies_queries_by_handle_only(run) -> None:
    """It joins to the analysis CSV by `query_id`. It does not restate the words."""
    text = (run.directory / "routing_issues.csv").read_text(encoding="utf-8")
    assert "search_term" not in text.splitlines()[0]
    assert "query_id" in text.splitlines()[0]
    for item in run.analysed:
        assert item.row.term.reveal() not in text


def test_the_actions_report_carries_no_raw_queries(run) -> None:
    """This is the file people forward and paste into messages."""
    text = (run.directory / "actions_report.txt").read_text(encoding="utf-8")
    for item in run.analysed:
        assert item.row.term.reveal() not in text, item.row.query_id
    assert run.analysed[0].row.query_id in text


def test_the_dashboard_carries_no_raw_queries(run) -> None:
    """The file most likely to be screenshotted."""
    text = (run.directory / "dashboard.html").read_text(encoding="utf-8")
    for item in run.analysed:
        assert item.row.term.reveal() not in text


def test_the_dashboard_is_self_contained(run) -> None:
    """No external stylesheet, script, font or image: it opens from a local folder."""
    text = (run.directory / "dashboard.html").read_text(encoding="utf-8")
    for forbidden in ("http://", "https://", "<script", "src=", "@import"):
        assert forbidden not in text, forbidden


def test_the_manifest_carries_no_raw_queries_and_no_key(run, query_key: QueryIdKey) -> None:
    text = (run.directory / "manifest.json").read_text(encoding="utf-8")
    for item in run.analysed:
        assert item.row.term.reveal() not in text
    secret = query_key.path.read_text(encoding="ascii").strip()
    assert secret not in text
    manifest = json.loads(text)
    assert manifest["query_ids"]["keyed"] is True
    assert manifest["query_ids"]["key_fingerprint"] == query_key.fingerprint


def test_the_manifest_records_that_no_threshold_was_set(run) -> None:
    """So a later reader knows the REVIEW verdicts were policy, not a bug."""
    manifest = json.loads((run.directory / "manifest.json").read_text(encoding="utf-8"))
    assert all(value is None for value in manifest["thresholds"].values())


def test_the_analysis_csv_does_carry_the_words(run) -> None:
    """The sanctioned exemption: you cannot judge a query you cannot read."""
    text = (run.directory / "search_term_analysis.csv").read_text(encoding="utf-8")
    assert all(item.row.term.reveal() in text for item in run.analysed)


def test_the_suggestions_file_holds_conflicts_too(run) -> None:
    """Splitting them would let a refusal read as an omission."""
    text = (run.directory / "negatives_suggestions.csv").read_text(encoding="utf-8")
    assert "status" in text.splitlines()[0]
    assert "SUGGESTION" in text


def test_the_report_explains_why_every_row_says_review(run) -> None:
    text = (run.directory / "actions_report.txt").read_text(encoding="utf-8")
    assert "Stage 1 sets no thresholds" in text
    assert "A person decides" in text


def test_the_report_states_that_nothing_was_changed(run) -> None:
    text = (run.directory / "actions_report.txt").read_text(encoding="utf-8")
    assert "changed nothing" in text
    assert "no access to your Google Ads account" in text


# ------------------------------------------------------------------ writeback


def test_writeback_emits_new_files_only(run) -> None:
    """The four-sheet source is never written to."""
    directory = run.directory / "writeback"
    assert directory.is_dir()
    names = {path.name for path in directory.iterdir()}
    assert names == {"03_KEYWORDS_append.csv", "01_ACTIONS_append.csv", "HOW_TO_PASTE.txt"}


def test_writeback_never_touches_the_workbook(
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    schema: WorkbookSchema,
    watchdog_config: Config,
    query_key: QueryIdKey,
    tmp_path: Path,
) -> None:
    """Proven by bytes, not by reading the code."""
    workbook = fixtures["clean"]
    before = workbook.read_bytes()
    bundle = parse_workbook(workbook, schema)
    execute(
        bundle,
        watchdog_config,
        query_key,
        search_terms=exports["clean"].parent,
        out_root=tmp_path,
        run_id="wd-untouched",
        propose_writeback=True,
    )
    assert workbook.read_bytes() == before


def test_writeback_rows_arrive_as_proposed(run) -> None:
    """The compiler treats an unapproved row as unapproved. A human sets the status."""
    text = (run.directory / "writeback" / "03_KEYWORDS_append.csv").read_text(encoding="utf-8")
    assert "PROPOSED" in text
    assert "APPROVED" not in text


def test_writeback_excludes_routing_conflicts(run) -> None:
    """A paste-ready row is an invitation to paste, and these were deliberately refused."""
    text = (run.directory / "writeback" / "03_KEYWORDS_append.csv").read_text(encoding="utf-8")
    withheld = [c for c in run.candidates if c.status == "ROUTING_CONFLICT"]
    for candidate in withheld:
        assert candidate.text not in text


def test_writeback_preserves_the_approved_destination_list(run) -> None:
    """`List name` was hard-coded to ACCOUNT_JUNK for every account-level candidate.

    An approved `ROUTE_COMPETITORS` entry therefore came back as junk vocabulary, and next
    Friday the taxonomy would classify the same term as junk rather than competitor — the
    Watchdog rewriting the meaning of its own evidence across weeks.
    """
    import csv

    text = (run.directory / "writeback" / "03_KEYWORDS_append.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    suggested = {c.text: c for c in run.candidates if c.status == "SUGGESTION"}
    assert rows, "the fixture must produce at least one suggestion"
    for row in rows:
        candidate = suggested[row["Keyword text"]]
        assert row["List name"] == candidate.destination_list
        assert row["List name"], "a candidate must never be written with no list"


def test_writeback_never_relabels_a_competitor_negative_as_junk(run) -> None:
    """Stated as its own test because it is the specific regression."""
    import csv

    text = (run.directory / "writeback" / "03_KEYWORDS_append.csv").read_text(encoding="utf-8")
    for row in csv.DictReader(text.splitlines()):
        candidate = next(c for c in run.candidates if c.text == row["Keyword text"])
        if candidate.destination_list != "ACCOUNT_JUNK":
            assert row["List name"] != "ACCOUNT_JUNK", row


def test_the_writeback_readme_says_nothing_was_applied(run) -> None:
    text = (run.directory / "writeback" / "HOW_TO_PASTE.txt").read_text(encoding="utf-8")
    assert "NOT changes" in text
    assert "was NOT modified" in text


# -------------------------------------------------------------------- staging


def test_a_failed_run_leaves_no_partial_directory(
    fixtures: dict[str, Path],
    schema: WorkbookSchema,
    watchdog_config: Config,
    query_key: QueryIdKey,
    tmp_path: Path,
) -> None:
    """A half-written analysis that looks complete is worse than none."""
    from apex_ads.watchdog.ingest import ExportError

    bundle = parse_workbook(fixtures["clean"], schema)
    with pytest.raises(ExportError):
        execute(
            bundle,
            watchdog_config,
            query_key,
            search_terms=tmp_path / "absent",
            out_root=tmp_path,
            run_id="wd-fail",
        )
    assert not list(tmp_path.glob("*.partial"))


def test_a_completed_run_is_never_overwritten(
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    schema: WorkbookSchema,
    watchdog_config: Config,
    query_key: QueryIdKey,
    tmp_path: Path,
) -> None:
    bundle = parse_workbook(fixtures["clean"], schema)
    kwargs = dict(search_terms=exports["clean"].parent, out_root=tmp_path, run_id="wd-same")
    execute(bundle, watchdog_config, query_key, **kwargs)
    with pytest.raises(FileExistsError):
        execute(bundle, watchdog_config, query_key, **kwargs)
    assert not list(tmp_path.glob("*.partial"))


def test_output_is_deterministic(
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    schema: WorkbookSchema,
    watchdog_config: Config,
    query_key: QueryIdKey,
    tmp_path: Path,
) -> None:
    """Two runs over one export produce byte-identical analysis."""
    bundle = parse_workbook(fixtures["clean"], schema)
    first = execute(
        bundle,
        watchdog_config,
        query_key,
        search_terms=exports["clean"].parent,
        out_root=tmp_path / "a",
        run_id="r",
    )
    second = execute(
        bundle,
        watchdog_config,
        query_key,
        search_terms=exports["clean"].parent,
        out_root=tmp_path / "b",
        run_id="r",
    )
    for name in ("search_term_analysis.csv", "negatives_suggestions.csv", "routing_issues.csv"):
        assert (first.directory / name).read_bytes() == (second.directory / name).read_bytes()
