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
        "negative_observations.csv",
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

    The contract this defends is the narrow one: raw query text has **one intentional
    output path**. It is not a proof that no string this system prints can ever coincide
    with a search — account configuration is written by people and could spell anything.
    The known coincidence paths are guarded separately; see the equality test below.
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


def test_the_observations_file_holds_both_kinds(run) -> None:
    """Splitting them would let a refusal read as an omission."""
    text = (run.directory / "negative_observations.csv").read_text(encoding="utf-8")
    assert "observation" in text.splitlines()[0]
    assert "what_to_do" in text.splitlines()[0]


def test_the_report_explains_why_every_row_says_review(run) -> None:
    text = (run.directory / "actions_report.txt").read_text(encoding="utf-8")
    assert "Stage 1 sets no thresholds" in text
    assert "A person decides" in text


def test_the_report_states_that_nothing_was_changed(run) -> None:
    text = (run.directory / "actions_report.txt").read_text(encoding="utf-8")
    assert "changed nothing" in text
    assert "no access to your Google Ads account" in text


# ------------------------------------------------------------------ writeback


def test_writeback_emits_an_actions_file_and_no_keyword_file(run) -> None:
    """The absence of `03_KEYWORDS_append.csv` is the deliverable.

    Stage 1's Watchdog does not author negative policy, so it has nothing to put in a
    keyword row. The version that emitted one produced invalid output twice over: "add
    `job` to ACCOUNT_JUNK" when `job` was already there, and a `Shared list → …` scope
    naming full campaign names where the workbook uses short aliases.
    """
    directory = run.directory / "writeback"
    assert directory.is_dir()
    names = {path.name for path in directory.iterdir()}
    assert names == {"01_ACTIONS_append.csv", "HOW_TO_PASTE.txt"}
    assert not list(run.directory.rglob("03_KEYWORDS_append.csv"))


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


def test_the_actions_file_says_the_watchdog_proposes_nothing(run) -> None:
    text = (run.directory / "writeback" / "01_ACTIONS_append.csv").read_text(encoding="utf-8")
    assert "Watchdog" in text
    assert "proposes no change" in text or "decide and" in text


def test_the_writeback_readme_says_nothing_was_applied(run) -> None:
    text = (run.directory / "writeback" / "HOW_TO_PASTE.txt").read_text(encoding="utf-8")
    assert "NOT a change" in text
    assert "was NOT modified" in text
    assert "no keyword file" in text


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
    for name in ("search_term_analysis.csv", "negative_observations.csv", "routing_issues.csv"):
        assert (first.directory / name).read_bytes() == (second.directory / name).read_bytes()


# --------------------------------------- privacy when a query equals configuration


@pytest.fixture()
def equality_run(
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    schema: WorkbookSchema,
    watchdog_config: Config,
    query_key: QueryIdKey,
    tmp_path: Path,
):
    """A run whose queries are exactly an approved negative and an approved keyword."""
    bundle = parse_workbook(fixtures["clean"], schema)
    return execute(
        bundle,
        watchdog_config,
        query_key,
        search_terms=exports["equality"].parent,
        out_root=tmp_path,
        run_id="wd-equality",
        propose_writeback=True,
        write_dashboard=True,
    )


def test_a_query_identical_to_an_approved_negative_does_not_leak(equality_run) -> None:
    """The leak was never through `SearchTerm`. It was through equality.

    `job` is on `ACCOUNT_JUNK`, so the system prints it for entirely legitimate reasons —
    and when somebody searches exactly `job`, printing the negative prints the query.
    Guarding `reveal()` cannot close that; withholding the label does.

    This covers the negative-text path. It is a guarded path, not a general proof — a
    future output that prints some other piece of account configuration verbatim would
    need the same guard.
    """
    queries = [item.row.term.reveal() for item in equality_run.analysed]
    assert "job" in queries, "the fixture must contain the equality case"

    revealing = set()
    for path in sorted(equality_run.directory.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(_contains_word(text, query) for query in queries):
            revealing.add(path.relative_to(equality_run.directory).as_posix())

    assert revealing == CARRIES_WORDS, (
        f"exactly one artifact may hold raw queries; these do: {sorted(revealing)}"
    )


def test_the_withholding_note_points_at_the_one_allowed_file(equality_run) -> None:
    """Losing the word must not lose the operator."""
    from apex_ads.watchdog.labels import WITHHELD

    text = (equality_run.directory / "negative_observations.csv").read_text(encoding="utf-8")
    assert WITHHELD in text
    assert "search_term_analysis.csv" in WITHHELD


def test_a_query_identical_to_an_approved_keyword_does_not_leak(equality_run) -> None:
    """For every exact-match keyword the keyword text IS the search term."""
    text = (equality_run.directory / "routing_issues.csv").read_text(encoding="utf-8")
    assert "triggering_keyword" not in text.splitlines()[0]
    report = (equality_run.directory / "actions_report.txt").read_text(encoding="utf-8")
    assert not _contains_word(report, "apex hospital")


def _contains_word(text: str, query: str) -> bool:
    """Substring matching, but not fooled by a query that is a substring of another word.

    `job` appears inside `jobs` and inside no word here, but the naive check would also
    fire on the file path or on `job` inside a longer sentence the tool legitimately wrote.
    """
    import re

    return re.search(rf"(?<![\w-]){re.escape(query)}(?![\w-])", text) is not None


# ----------------------------------------------- a partial total is worse than none


@pytest.fixture()
def partial_run(
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    schema: WorkbookSchema,
    watchdog_config: Config,
    query_key: QueryIdKey,
    tmp_path: Path,
):
    """A run over an export with unreadable rows, one of which has an unreadable cost."""
    bundle = parse_workbook(fixtures["clean"], schema)
    return execute(
        bundle,
        watchdog_config,
        query_key,
        search_terms=exports["parse_errors"].parent,
        out_root=tmp_path,
        run_id="wd-partial",
        propose_writeback=True,
        write_dashboard=True,
    )


def test_spend_is_not_stated_as_a_total_when_rows_could_not_be_read(partial_run) -> None:
    """The headline used to print a confident figure computed from readable rows only.

    Somebody compares that number to last week's. A quietly partial total is worse than an
    admitted unknown, because it looks like the same measurement and is not.
    """
    assert partial_run.export.parse_errors, "the fixture must contain unreadable rows"
    assert not partial_run.export.spend_is_complete

    headline = next(
        line
        for line in (partial_run.directory / "actions_report.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.startswith("Spend:")
    )
    assert "TOTAL UNKNOWN" in headline, headline
    assert "across readable rows" in headline, headline


def test_the_summary_no_longer_names_a_finding_that_does_not_exist(run) -> None:
    """The label outlived the finding: the block still said "Held demand"."""
    text = (run.directory / "actions_report.txt").read_text(encoding="utf-8")
    assert "Held demand" not in text
    assert "EXPLICIT_KEYWORD_GAP" in text
    assert "Coverage unknown" in text


# ------------------------------------- one canonical answer, rendered everywhere


@pytest.fixture()
def dated_run(
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    schema: WorkbookSchema,
    watchdog_config: Config,
    query_key: QueryIdKey,
    tmp_path: Path,
):
    """The clean export: declared 2026-08-11..17, with activity stopping on the 16th."""
    from datetime import date

    bundle = parse_workbook(fixtures["clean"], schema)
    return execute(
        bundle,
        watchdog_config,
        query_key,
        search_terms=exports["clean"].parent,
        out_root=tmp_path,
        run_id="wd-dated",
        today=date(2026, 8, 18),
        propose_writeback=True,
        write_dashboard=True,
    )


def test_every_output_surface_reports_the_same_selected_window(dated_run) -> None:
    """Ingest learned the difference; three consumers did not receive the memo.

    `read_export` correctly separated the declared window from the days that served, and
    stopped warning about a quiet last day. But the report, the dashboard and the manifest
    each reached for the activity range independently, so a run whose own validator said
    "correct 7-day export" produced three artifacts all describing a 6-day one.
    """
    from datetime import date

    assert dated_run.export.declared_range == (date(2026, 8, 11), date(2026, 8, 17))
    assert dated_run.export.activity_range == (date(2026, 8, 11), date(2026, 8, 16))
    assert dated_run.export.selected_range == (date(2026, 8, 11), date(2026, 8, 17))

    report = (dated_run.directory / "actions_report.txt").read_text(encoding="utf-8")
    covering = next(line for line in report.splitlines() if line.startswith("Covering:"))
    assert "2026-08-11 to 2026-08-17" in covering, covering
    assert "2026-08-16" not in covering

    dashboard = (dated_run.directory / "dashboard.html").read_text(encoding="utf-8")
    assert "2026-08-11 to 2026-08-17" in dashboard

    manifest = json.loads((dated_run.directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["export"]["covers"] == {
        "first": "2026-08-11",
        "last": "2026-08-17",
        "source": "declared",
    }
    # ...and the activity range survives beside it, because an audit needs both.
    assert manifest["export"]["activity_range"]["last"] == "2026-08-16"
    assert manifest["export"]["declared_range"] == {"first": "2026-08-11", "last": "2026-08-17"}


def test_a_declared_range_with_no_day_column_is_not_reported_as_unknown(
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    schema: WorkbookSchema,
    watchdog_config: Config,
    query_key: QueryIdKey,
    tmp_path: Path,
) -> None:
    """The report hard-coded "no day column" as the reason a range is unknown.

    An export can print a perfectly good selected range and carry no Day column at all —
    that is the common shape. The validator accepted it; the header still told the reader
    the period was unverified.
    """
    bundle = parse_workbook(fixtures["clean"], schema)
    run = execute(
        bundle,
        watchdog_config,
        query_key,
        search_terms=exports["no_day_column"].parent,
        out_root=tmp_path,
        run_id="wd-no-day",
        write_dashboard=True,
    )
    assert run.export.activity_range == (None, None)
    assert run.export.declared_range is not None

    report = (run.directory / "actions_report.txt").read_text(encoding="utf-8")
    covering = next(line for line in report.splitlines() if line.startswith("Covering:"))
    assert "UNKNOWN" not in covering, covering
    assert "2026-08-11 to 2026-08-17" in covering


def test_the_dashboard_does_not_present_a_partial_subtotal_as_spend(partial_run) -> None:
    """The text report was made honest about partial spend. The screenshot was not.

    This is the artifact people forward as a picture, so a readable-row subtotal rendered
    under the bare word "spend" is the version that travels.
    """
    assert not partial_run.export.spend_is_complete

    dashboard = (partial_run.directory / "dashboard.html").read_text(encoding="utf-8")
    assert "readable-row reported search-term spend" in dashboard
    assert ">spend<" not in dashboard
    assert "TOTAL UNKNOWN" in dashboard

    # ...and it says the same thing the text report says, from the same source.
    report = (partial_run.directory / "actions_report.txt").read_text(encoding="utf-8")
    assert "TOTAL UNKNOWN" in report


def test_the_manifest_hashes_nested_writeback_artifacts(dated_run) -> None:
    """`iterdir()` stopped at the top level, so `writeback/` was outside the fingerprint.

    Those two files are the ones a person is told to paste into the operating system. Every
    output that only a machine reads was covered; the ones with human consequences were not.
    """
    manifest = json.loads((dated_run.directory / "manifest.json").read_text(encoding="utf-8"))
    hashed = {entry["name"] for entry in manifest["files"]}

    on_disk = {
        path.relative_to(dated_run.directory).as_posix()
        for path in dated_run.directory.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert hashed == on_disk, sorted(on_disk - hashed)
    assert "writeback/01_ACTIONS_append.csv" in hashed
    assert "writeback/HOW_TO_PASTE.txt" in hashed


def test_the_summary_separates_no_exact_keyword_from_the_gap_finding(run) -> None:
    """Two different denominators under one label.

    `no_own` counts every query with no exact keyword of its own. The finding fires only
    where the query was covered, converted, and still had none. Labelling the first as "the
    EXPLICIT_KEYWORD_GAP test" made the summary disagree with the section below it.
    """
    from apex_ads.watchdog.findings import FindingType

    gaps = [f for f in run.term_findings if f.type is FindingType.EXPLICIT_KEYWORD_GAP]
    report = (run.directory / "actions_report.txt").read_text(encoding="utf-8")

    opportunities = next(
        line for line in report.splitlines() if "Explicit-keyword opportunities" in line
    )
    assert opportunities.split()[2] == str(len(gaps)), opportunities

    no_exact = next(line for line in report.splitlines() if "Workbook has no exact keyword" in line)
    assert int(no_exact.split()[-1]) > len(gaps), "the fixture must make the two differ"
    assert "EXPLICIT_KEYWORD_GAP" not in no_exact
    # ...and it claims nothing about *what* served those queries. The count includes rows
    # whose triggering keyword is unapproved or unknown, for which no such claim is available.
    assert "broader keyword" not in no_exact


def test_the_result_points_at_the_files_it_says_it_wrote(dated_run) -> None:
    """`final / item.name` flattened the two nested writeback paths.

    The files were on disk and in the manifest; the result object pointed at
    `<run>/01_ACTIONS_append.csv`, which does not exist. Nothing consumes this property
    today, and that is exactly why it was worth fixing before Phase 7 starts consuming it —
    a knowingly false artifact list is a bug waiting for its first caller.
    """
    assert dated_run.files
    missing = [path for path in dated_run.files if not path.is_file()]
    assert not missing, missing

    relative = {path.relative_to(dated_run.directory).as_posix() for path in dated_run.files}
    assert "writeback/01_ACTIONS_append.csv" in relative
    assert "writeback/HOW_TO_PASTE.txt" in relative


# --------------------------------- what the evidence entitles the report to say


def test_no_output_calls_the_disclosed_total_campaign_spend(dated_run) -> None:
    """Google omits low-volume queries for privacy. Summing rows is not campaign spend.

    The arithmetic was never wrong; the label was. A number under the bare word "spend" is
    read as the campaign's budget, and concentration is precisely the metric where an
    inflated denominator changes what a person decides — "34% of Neuro spend" may be 20% of
    what Neuro actually spent.
    """
    report = (dated_run.directory / "actions_report.txt").read_text(encoding="utf-8")
    dashboard = (dated_run.directory / "dashboard.html").read_text(encoding="utf-8")

    assert "reported search-term spend" in report
    assert "reported search-term spend" in dashboard.lower()

    # The denominator is named wherever a share is quoted.
    shares = [line for line in report.splitlines() if "% of" in line]
    assert shares, "the fixture must produce a concentration row"
    for line in shares:
        assert "reported search-term spend" in line, line

    # And the omission is stated in its own right, on every run, not only when it bites.
    assert "WHAT THIS FILE DOES NOT CONTAIN" in report
    assert "REPORTED SEARCH-TERM SPEND" in report


def test_the_operator_is_not_told_to_investigate_an_intentional_exclusion(
    fixtures: dict[str, Path],
    exports: dict[str, Path],
    schema: WorkbookSchema,
    watchdog_config: Config,
    query_key: QueryIdKey,
    tmp_path: Path,
) -> None:
    """The false action was removed from the CSV and recreated in the prose.

    `negative_observations.csv` holds both kinds of row. Telling the operator to "check
    whether the list is actually applied" for the whole file means telling them to
    investigate `INTENTIONAL_NON_REACH` — where the answer is that the list deliberately
    does not cover that campaign. A hurried reader applies it, reversing a frozen decision.
    """
    bundle = parse_workbook(fixtures["clean"], schema)
    run = execute(
        bundle,
        watchdog_config,
        query_key,
        search_terms=exports["clean"].parent,
        out_root=tmp_path,
        run_id="wd-instructions",
        propose_writeback=True,
    )
    report = (run.directory / "actions_report.txt").read_text(encoding="utf-8")

    steps = report.split("WHAT TO DO WITH THIS")[1]
    assert "INTENTIONAL_NON_REACH" in steps
    assert "OBSERVED_DESPITE_NEGATIVE" in steps

    intentional = steps.split("INTENTIONAL_NON_REACH")[1].split("OBSERVED_DESPITE_NEGATIVE")[0]
    assert "Do NOT investigate" in intentional
    assert "Information only" in intentional

    observed = steps.split("OBSERVED_DESPITE_NEGATIVE")[1]
    assert "actually applied" in observed


def test_the_report_does_not_claim_every_row_says_review(run) -> None:
    """A shipped fixture row says FLAGGED, so the explanation was demonstrably false.

    Junk vocabulary already on an approved negative list is a deterministic hit on a human
    decision — no statistic to be careful about — and it is FLAGGED with every Stage-1
    threshold still null. The behaviour is right; the sentence above it was not.
    """
    from apex_ads.watchdog.findings import FLAGGED

    flagged = [finding for finding in run.term_findings if finding.verdict == FLAGGED]
    assert flagged, "the fixture must exercise the approved-vocabulary branch"

    report = (run.directory / "actions_report.txt").read_text(encoding="utf-8")
    dashboard = (run.directory / "dashboard.html").read_text(encoding="utf-8")
    assert "EVERY ROW SAYS" not in report.upper()
    assert "Every row says REVIEW" not in dashboard
    assert "Rows can still say FLAGGED" in report


def test_the_manifest_carries_the_same_denominator_warning_the_report_does(dated_run) -> None:
    """A program reading the manifest must not be told less than a person reading the report.

    The report said "reported search-term spend, Google may be hiding queries". The manifest
    said `spend_is_complete: true` and nothing else — a caveat that exists only in prose is
    a caveat Phase 7 will inherit as a bare number.
    """
    manifest = json.loads((dated_run.directory / "manifest.json").read_text(encoding="utf-8"))
    export = manifest["export"]

    assert export["reported_search_term_spend"] == str(dated_run.export.total_cost)
    assert export["returned_rows_parse_complete"] is True
    assert export["search_term_visibility"] == {
        "state": "NO_WITHHELD_AGGREGATE",
        "epistemic": "NOT_PROVABLY_COMPLETE",
        "withheld_cost": None,
    }
    assert export["undisclosed_cost"] is None
    assert export["aggregate_rows_seen"] == []

    # `spend_is_complete` was the ambiguous name: it answers "did our parser read every
    # returned row", and was being read as "is this the whole spend".
    assert "spend_is_complete" not in export

    # WD-007 itself, because the Watchdog writes no findings.json — that is the compiler's
    # artifact, and the audit record claiming otherwise was wrong.
    visibility = [item for item in manifest["findings"] if item["rule_id"] == "WD-007"]
    assert visibility, manifest["findings"]
    assert "REPORTED SEARCH-TERM SPEND" in visibility[0]["message"]
    # ...and it is the same sentence the report and the dashboard print, not a variant.
    assert visibility[0]["message"] == dated_run.export.visibility.paragraph
    report = (dated_run.directory / "actions_report.txt").read_text(encoding="utf-8")
    assert dated_run.export.visibility.paragraph in report
    assert not (dated_run.directory / "findings.json").exists()
