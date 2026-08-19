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
