"""Watchdog ingest: the raw term boundary and the fail-closed reader (spec §13.1).

The arrow under test is *raw Google search term → ingest*. Everything downstream trusts
that a query became a protected `SearchTerm` here and nowhere later, so these tests attack
the reader's failure paths as hard as its success path — a failure path is exactly where a
raw query gets quoted into a message by accident.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from apex_ads.models.config import Config
from apex_ads.util.queryid import QueryIdKey
from apex_ads.watchdog.ingest import ExportError, choose_export, read_export


def test_a_clean_export_is_read(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    export = read_export(
        exports["clean"], watchdog_config.rules.watchdog, query_key, today=date(2026, 8, 18)
    )
    assert len(export.rows) == 9
    assert not export.parse_errors
    assert export.activity_range == (date(2026, 8, 11), date(2026, 8, 16))


def test_the_header_row_is_found_by_content_not_by_position(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Real exports carry a title and a date line above the table.

    Counting lines would be the row-index mistake the workbook parser exists to avoid, and
    Google has changed that preamble before.
    """
    text = exports["clean"].read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("Search terms report")
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    assert export.rows


def test_every_row_carries_a_protected_term(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The boundary. Nothing after ingest may be able to print a query."""
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    for row in export.rows:
        assert row.term.keyed is True
        assert row.query_id.startswith("q")
        with pytest.raises(AttributeError):
            row.term.__dict__  # noqa: B018 - reading it is the attack


def test_a_missing_required_column_blocks_and_produces_nothing(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Fail closed, like the compiler. A half-read export hides the half it missed."""
    with pytest.raises(ExportError) as caught:
        read_export(exports["missing_column"], watchdog_config.rules.watchdog, query_key)
    finding = caught.value.finding
    assert finding.rule_id == "WD-001"
    assert "cost" in finding.message
    assert "conversions" in finding.message


def test_a_duplicated_column_is_refused(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """`ING-007` in a different file format: the reader must not pick one of two."""
    with pytest.raises(ExportError) as caught:
        read_export(exports["duplicate_column"], watchdog_config.rules.watchdog, query_key)
    assert caught.value.finding.rule_id == "WD-001"
    assert "repeats" in caught.value.finding.message


def test_unreadable_rows_are_counted_never_dropped(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    export = read_export(exports["parse_errors"], watchdog_config.rules.watchdog, query_key)
    assert len(export.parse_errors) == 2
    categories = {error.category for error in export.parse_errors}
    assert categories == {"short_row", "unreadable_metric"}
    assert any(finding.rule_id == "WD-004" for finding in export.findings)


def test_a_parse_error_carries_no_query_text(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Row ID, file, hashed query ID, category, error code — and nothing quotable."""
    export = read_export(exports["parse_errors"], watchdog_config.rules.watchdog, query_key)
    for error in export.parse_errors:
        rendered = str(error.as_record())
        assert "bad cost row" not in rendered
        assert "half a row" not in rendered
        assert error.code.startswith("WD-E")
        assert error.row > 0


def test_a_stale_export_warns_and_names_the_range(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Reviewing last month's data by accident is a quiet way to decide badly."""
    export = read_export(
        exports["stale"], watchdog_config.rules.watchdog, query_key, today=date(2026, 8, 18)
    )
    stale = [finding for finding in export.findings if finding.rule_id == "WD-003"]
    assert stale
    assert "2025-01" in " ".join(finding.message for finding in stale)


def test_an_empty_export_is_reported_rather_than_read_as_a_quiet_week(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    export = read_export(exports["empty"], watchdog_config.rules.watchdog, query_key)
    assert not export.rows
    assert any(finding.rule_id == "WD-005" for finding in export.findings)


def test_a_directory_yields_the_most_recent_csv(tmp_path: Path) -> None:
    import os
    import time

    older = tmp_path / "a.csv"
    newer = tmp_path / "b.csv"
    older.write_text("x", encoding="utf-8")
    newer.write_text("y", encoding="utf-8")
    past = time.time() - 500
    os.utime(older, (past, past))
    assert choose_export(tmp_path) == newer


def test_an_empty_directory_blocks_rather_than_reporting_on_nothing(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as caught:
        choose_export(tmp_path)
    assert caught.value.finding.rule_id == "WD-002"


def test_a_missing_path_blocks(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as caught:
        choose_export(tmp_path / "nope")
    assert caught.value.finding.rule_id == "WD-002"


# ------------------------------------ row provenance and the weekly date range


def test_row_numbers_are_the_real_csv_lines(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The operator is sent to a line. It must be the right line.

    A real export carries a title line, a date line and a blank before the header, so the
    first data row is line 5. `enumerate(reader, start=2)` reported it as 2 — with a
    comment claiming that matched the spreadsheet — so every reference in
    `parse_errors.csv` and every `source_row` was three lines short.
    """
    path = exports["clean"]
    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = next(i for i, line in enumerate(lines, start=1) if line.startswith("Day,"))
    assert header_index == 4, "the fixture must carry a realistic preamble"

    export = read_export(path, watchdog_config.rules.watchdog, query_key)
    assert export.rows[0].term.row == header_index + 1 == 5

    # and the line it names really is that row in the file
    first_query = export.rows[0].term.reveal()
    assert first_query in lines[export.rows[0].term.row - 1]


def test_parse_error_rows_point_at_the_real_line(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    path = exports["parse_errors"]
    lines = path.read_text(encoding="utf-8").splitlines()
    export = read_export(path, watchdog_config.rules.watchdog, query_key)
    assert export.parse_errors
    for error in export.parse_errors:
        assert 1 <= error.row <= len(lines)
        assert lines[error.row - 1].strip(), "a reported line must not be blank"


def test_the_range_is_read_from_the_date_line_when_there_is_no_day_column(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Real exports often have no Day column. The range is still stated above the table."""
    from datetime import date

    export = read_export(
        exports["no_day_column"], watchdog_config.rules.watchdog, query_key, today=date(2026, 8, 18)
    )
    assert export.activity_range == (None, None)
    assert export.declared_range == (date(2026, 8, 11), date(2026, 8, 17))
    # 7 days, ending yesterday: exactly the procedure, so no complaint.
    assert not [f for f in export.findings if f.rule_id == "WD-003"]


def test_an_unverifiable_range_is_warned_about_rather_than_assumed_correct(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """No Day column and no readable date line.

    Silence here let a thirty-day export pass as "the previous 7 days" — for a tool whose
    whole procedure is a weekly cadence, that is too permissive.
    """
    export = read_export(exports["unverifiable"], watchdog_config.rules.watchdog, query_key)
    assert export.activity_range == (None, None)
    assert export.declared_range is None
    stale = [f for f in export.findings if f.rule_id == "WD-003"]
    assert stale
    assert "could not be established" in stale[0].message


def test_a_seven_day_activity_span_does_not_verify_the_selected_window(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """A fallback may describe uncertainty. It may not promote itself into evidence.

    The previous fix made the declared range the authority for *describing* the run, but
    where none was printed the activity span was still allowed to *verify* it. So a
    July 19 - August 17 selection whose traffic all fell in the last week produced exactly
    seven observed days and cleared the window check in silence — the original defect, in
    the one shape nobody would think to test for, because the numbers look right.

    The fixture is that shape: seven consecutive active days, no readable date line.
    """
    from apex_ads.watchdog.ingest import UNVERIFIED_WINDOW

    export = read_export(
        exports["seven_active_days"],
        watchdog_config.rules.watchdog,
        query_key,
        today=date(2026, 8, 18),
    )
    first, last = export.activity_range
    assert first is not None and last is not None
    assert (last - first).days + 1 == watchdog_config.rules.watchdog.lookback_days
    assert export.declared_range is None

    warnings = [finding for finding in export.findings if finding.rule_id == "WD-003"]
    assert warnings, "a tidy Day column is not evidence about the selected window"
    assert any(UNVERIFIED_WINDOW in finding.message for finding in warnings)

    # ...and the run still describes itself honestly rather than claiming the window.
    assert export.range_source == "activity"


def test_a_declared_window_is_still_the_thing_that_gets_verified(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The other half, which the fix must not break.

    A declared seven-day range with a quiet last day is correct and stays silent; that is
    the whole point of separating the two sources, and tightening one must not undo it.
    """
    export = read_export(
        exports["clean"], watchdog_config.rules.watchdog, query_key, today=date(2026, 8, 18)
    )
    assert export.declared_range == (date(2026, 8, 11), date(2026, 8, 17))
    assert export.activity_range == (date(2026, 8, 11), date(2026, 8, 16))
    assert not [finding for finding in export.findings if finding.rule_id == "WD-003"]


def test_googles_own_total_rows_are_never_read_as_searches(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """`Total: Search terms` is a column footer, not something a patient typed.

    Nothing told them apart. Both summary rows were parsed as queries, handed query IDs,
    run through the taxonomy, and their money added to the total — so a file whose real
    disclosed spend was 1,430 reported 10,860, double counted, with two of its "searches"
    being Google's own arithmetic.
    """
    export = read_export(
        exports["aggregates"], watchdog_config.rules.watchdog, query_key, today=date(2026, 8, 18)
    )
    revealed = [row.term.reveal() for row in export.rows]
    assert len(export.rows) == 2, revealed
    assert not [text for text in revealed if text.lower().startswith("total")]

    assert {item.label for item in export.aggregates} == {
        "Total: Other search terms",
        "Total: Search terms",
    }
    assert export.total_cost == Decimal("1430.00")


def test_the_withheld_query_total_is_kept_as_evidence_not_dropped(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """`Total: Other search terms` is the only thing the file says about what it hides.

    Google omits low-volume queries for privacy. Discarding the aggregate along with the
    grand total would have thrown away the one number that lets a reader judge how much of
    the campaign this report never showed them.
    """
    export = read_export(
        exports["aggregates"], watchdog_config.rules.watchdog, query_key, today=date(2026, 8, 18)
    )
    assert export.undisclosed_cost == Decimal("4000.00")
    assert export.spend_is_complete, "no row failed to parse — that is a separate question"
    assert export.search_term_visibility == "WITHHELD_ACTIVITY_CONFIRMED"

    visibility = [finding for finding in export.findings if finding.rule_id == "WD-007"]
    assert visibility, "every run states what the report does not contain"
    assert "reported search-term spend" in visibility[0].message


def test_an_export_with_no_aggregate_row_still_admits_the_gap(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Absence of the aggregate is not evidence that nothing was withheld.

    The normal case: no `Other search terms` row at all. `undisclosed_cost` is None — "not
    stated" — and the visibility note still fires, because Google's omission is a property
    of the report rather than of this file.
    """
    export = read_export(
        exports["clean"], watchdog_config.rules.watchdog, query_key, today=date(2026, 8, 18)
    )
    assert export.undisclosed_cost is None
    # "Not provably complete", not "definitely incomplete". Google *can* omit low-volume
    # queries; that this particular week has any is not something the file establishes.
    assert export.search_term_visibility == "NOT_PROVABLY_COMPLETE"
    assert [finding for finding in export.findings if finding.rule_id == "WD-007"]


def test_a_seven_day_range_from_the_wrong_week_is_warned_about(
    watchdog_config: Config, tmp_path: Path
) -> None:
    """Span-is-seven plus not-too-old is not "the previous 7 days".

    2026-08-08 to 2026-08-14, read on 2026-08-18: seven consecutive days, four days old,
    and entirely the wrong week. Nothing about it looks unusual, which is exactly why it
    gets acted on. Google's own Last 7 days ends yesterday.
    """
    from apex_ads.watchdog.ingest import Export, _range_findings

    export = Export(path=tmp_path / "x.csv")
    export.declared_range = (date(2026, 8, 8), date(2026, 8, 14))
    export.activity_range = (date(2026, 8, 8), date(2026, 8, 14))

    findings = _range_findings(export, watchdog_config.rules.watchdog, today=date(2026, 8, 18))
    assert findings, "a seven-day span from the wrong week used to pass in silence"
    message = findings[0].message
    assert "2026-08-08 to 2026-08-14" in message
    assert "2026-08-11 to 2026-08-17" in message, message


def test_the_correct_previous_seven_days_still_passes(
    watchdog_config: Config, tmp_path: Path
) -> None:
    """The direction the tightening must not break."""
    from apex_ads.watchdog.ingest import Export, _range_findings

    export = Export(path=tmp_path / "x.csv")
    export.declared_range = (date(2026, 8, 11), date(2026, 8, 17))
    export.activity_range = (date(2026, 8, 11), date(2026, 8, 16))
    assert not _range_findings(export, watchdog_config.rules.watchdog, today=date(2026, 8, 18))


def test_an_unreadable_aggregate_cost_is_unknown_and_never_zero(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The doctrine this whole file exists to enforce, broken by the parser enforcing it.

    The first version of `_aggregate()` returned `Decimal("0")` on a bad cell. So an
    unreadable `Total: Other search terms` cost produced, in the report, *"Google states
    0.00 of spend on searches it did not name"* — a fabricated zero, in the one place whose
    entire job is to say how much we cannot see. Eleven audits of "unreadable is not zero"
    and the new footer parser walked straight past it.
    """
    export = read_export(
        exports["aggregate_unreadable"],
        watchdog_config.rules.watchdog,
        query_key,
        today=date(2026, 8, 18),
    )
    assert export.undisclosed_cost is None, "not stated, and certainly not zero"
    assert export.aggregates_unreadable

    aggregate = next(item for item in export.aggregates if item.undisclosed)
    assert aggregate.cost is None
    assert "cost" in aggregate.unreadable

    visibility = next(finding for finding in export.findings if finding.rule_id == "WD-007")
    assert "UNKNOWN" in visibility.message
    assert "0.00" not in visibility.message


def test_confirmed_withheld_activity_is_distinguished_from_merely_unproven(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """`demand_is_fully_visible = False` claimed more than Google's rules establish.

    Google *can* omit low-volume queries. That every seven-day Apex export necessarily has
    at least one omitted query is not something any file proves. So the default state is
    "not provably complete", and only Google's own aggregate — with traffic in it — upgrades
    that to confirmed.
    """
    confirmed = read_export(
        exports["aggregates"], watchdog_config.rules.watchdog, query_key, today=date(2026, 8, 18)
    )
    assert confirmed.search_term_visibility == "WITHHELD_ACTIVITY_CONFIRMED"

    unproven = read_export(
        exports["clean"], watchdog_config.rules.watchdog, query_key, today=date(2026, 8, 18)
    )
    assert unproven.search_term_visibility == "NOT_PROVABLY_COMPLETE"
    assert not hasattr(unproven, "demand_is_fully_visible")
