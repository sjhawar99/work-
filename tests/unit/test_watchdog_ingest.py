"""Watchdog ingest: the raw term boundary and the fail-closed reader (spec §13.1).

The arrow under test is *raw Google search term → ingest*. Everything downstream trusts
that a query became a protected `SearchTerm` here and nowhere later, so these tests attack
the reader's failure paths as hard as its success path — a failure path is exactly where a
raw query gets quoted into a message by accident.
"""

from __future__ import annotations

from datetime import date
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
    assert export.observed_dates == (date(2026, 8, 11), date(2026, 8, 16))


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
    assert export.observed_dates == (None, None)
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
    assert export.observed_dates == (None, None)
    assert export.declared_range is None
    stale = [f for f in export.findings if f.rule_id == "WD-003"]
    assert stale
    assert "could not be established" in stale[0].message
