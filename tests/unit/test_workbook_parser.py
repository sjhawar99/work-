"""Parsing the four-sheet workbook into typed records."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from apex_ads.ingest.errors import (
    CellCoercionError,
    MissingColumnError,
    MissingSectionError,
    UnknownRegistryTypeError,
)
from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import WorkbookSchema
from apex_ads.models.workbook import WorkbookBundle


@pytest.fixture(scope="module")
def clean(fixtures: dict[str, Path], schema: WorkbookSchema) -> WorkbookBundle:
    return parse_workbook(fixtures["clean"], schema)


# ------------------------------------------------------------------------ shape


def test_every_section_is_parsed(clean: WorkbookBundle) -> None:
    assert len(clean.blocking_actions) == 2
    assert len(clean.running_actions) == 2
    assert len(clean.campaigns) == 2
    assert len(clean.ad_groups) == 3
    assert len(clean.landing_pages) == 3
    assert len(clean.supporting_assets) == 2
    assert len(clean.measurement_contract) == 2
    assert len(clean.ads) == 3
    assert len(clean.keywords) == 3
    assert len(clean.negatives) == 5
    assert len(clean.daily_log) == 2


def test_provenance_is_on_every_record(clean: WorkbookBundle) -> None:
    records = [
        *clean.blocking_actions,
        *clean.running_actions,
        *clean.campaigns,
        *clean.ad_groups,
        *clean.landing_pages,
        *clean.supporting_assets,
        *clean.measurement_contract,
        *clean.ads,
        *clean.keywords,
        *clean.negatives,
        *clean.daily_log,
    ]
    assert records
    for record in records:
        assert record.sheet
        assert record.section
        assert record.row > 0


def test_file_provenance_is_recorded(clean: WorkbookBundle, fixtures: dict[str, Path]) -> None:
    assert clean.source_path == fixtures["clean"]
    assert len(clean.source_sha256) == 64
    assert clean.source_mtime is not None


def test_typed_values_are_typed(clean: WorkbookBundle) -> None:
    campaign = clean.campaigns[0]
    assert campaign.monthly_budget == Decimal("5000")
    assert campaign.avg_daily_budget == Decimal("164.47")
    assert campaign.launch_date == date(2026, 8, 27)
    assert clean.declared_monthly_total == Decimal("25000")


# ------------------------------------------------------------- the two action tables


def test_action_tables_keep_their_own_shapes(clean: WorkbookBundle) -> None:
    """Different columns, modelled separately rather than forced into one fake schema."""
    blocking = clean.blocking_actions[0]
    running = clean.running_actions[0]
    assert blocking.done_when == "CRM has one field"
    assert running.required_action == "Approve the budgets"
    assert running.date_raised == date(2026, 8, 18)
    assert not hasattr(blocking, "required_action")
    assert not hasattr(running, "done_when")


# ---------------------------------------------------------------------- 02 BUILD


def test_landing_pages_stay_paths(clean: WorkbookBundle) -> None:
    """Paths are preserved as written; joining base_url happens at check time (Phase 4)."""
    assert clean.landing_pages[0].planned_url == "/google/apex-jaipur"
    assert clean.ad_groups[0].planned_landing_page == "/google/apex-jaipur"
    assert all(page.planned_url.startswith("/") for page in clean.landing_pages)


def test_negative_list_cell_is_split_and_kept_raw(clean: WorkbookBundle) -> None:
    group = clean.ad_groups[0]
    assert group.negative_lists == ["ACCOUNT_JUNK", "OUTSIDE_GEO"]
    assert group.negative_lists_raw == "ACCOUNT_JUNK · OUTSIDE_GEO"


def test_rsa_is_unpivoted_into_typed_assets(clean: WorkbookBundle) -> None:
    ad = clean.ads[0]
    assert len(ad.headlines) == 12
    assert len(ad.descriptions) == 4
    assert ad.headlines[0].kind == "HEADLINE"
    assert ad.headlines[0].position == 1
    assert ad.headlines[0].column == "H1"
    assert ad.headlines[11].position == 12
    assert ad.descriptions[0].kind == "DESCRIPTION"
    assert ad.headline_texts[0] == "Core headline 1"


def test_rsa_handles_a_partial_asset_set(fixtures: dict[str, Path], schema: WorkbookSchema) -> None:
    """5 headlines is a business problem (AD-001, Phase 4), not a parsing problem."""
    bundle = parse_workbook(fixtures["wide_rsa"], schema)
    assert [asset.position for asset in bundle.ads[0].headlines] == [1, 2, 3, 4, 5]
    assert [asset.position for asset in bundle.ads[0].descriptions] == [1, 2]


# -------------------------------------------------------------------- 03 KEYWORDS


def test_registry_splits_on_type(clean: WorkbookBundle) -> None:
    assert {keyword.row_type for keyword in clean.keywords} == {"KEYWORD"}
    assert {negative.row_type for negative in clean.negatives} == {"NEGATIVE"}


def test_scope_survives_round_trip_unchanged(clean: WorkbookBundle) -> None:
    raw = {negative.scope.raw for negative in clean.negatives}
    assert "Account" in raw
    assert "Shared list → Neuro, Generic, Ortho, Nephro" in raw
    assert "Campaign: TST | Search | Neuro | Jaipur" in raw
    assert "Ad group" in raw


def test_scope_levels_are_interpreted(clean: WorkbookBundle) -> None:
    levels = {negative.scope.level for negative in clean.negatives}
    assert levels == {"ACCOUNT", "SHARED_LIST", "CAMPAIGN", "AD_GROUP"}

    shared = next(n for n in clean.negatives if n.scope.level == "SHARED_LIST")
    assert shared.scope.applied_campaigns == ["Neuro", "Generic", "Ortho", "Nephro"]

    campaign_scoped = next(n for n in clean.negatives if n.scope.level == "CAMPAIGN")
    assert campaign_scoped.scope.campaign == "TST | Search | Neuro | Jaipur"


def test_negative_level_reads_through_to_scope(clean: WorkbookBundle) -> None:
    for negative in clean.negatives:
        assert negative.level == negative.scope.level


def test_copy_paste_value_is_derived_not_trusted(clean: WorkbookBundle) -> None:
    """The workbook's value is kept; the tool regenerates its own for KW-009 to compare."""
    phrase = next(k for k in clean.keywords if k.match_type == "PHRASE")
    exact = next(k for k in clean.keywords if k.match_type == "EXACT")
    assert phrase.copy_paste_expected == f'"{phrase.text}"'
    assert exact.copy_paste_expected == f"[{exact.text}]"
    assert all(row.copy_paste_matches for row in clean.keywords + clean.negatives)


def test_null_tokens_become_none_not_empty_strings(clean: WorkbookBundle) -> None:
    account_negative = next(n for n in clean.negatives if n.scope.level == "ACCOUNT")
    assert account_negative.campaign is None
    assert account_negative.ad_group is None


# ------------------------------------------------------------------------ 04 DAILY


def test_daily_is_parsed_for_context_only(clean: WorkbookBundle) -> None:
    entry = clean.daily_log[0]
    assert entry.date == date(2026, 8, 27)
    assert entry.planned_daily_budget == Decimal("164.47")
    assert entry.spend is None


# -------------------------------------------------------------------- failures


def test_missing_section_fails_explicitly(
    fixtures: dict[str, Path], schema: WorkbookSchema
) -> None:
    with pytest.raises(MissingSectionError):
        parse_workbook(fixtures["missing_section"], schema)


def test_renamed_column_fails_explicitly(fixtures: dict[str, Path], schema: WorkbookSchema) -> None:
    with pytest.raises(MissingColumnError):
        parse_workbook(fixtures["renamed_column"], schema)


def test_malformed_currency_never_becomes_nan(
    fixtures: dict[str, Path], schema: WorkbookSchema
) -> None:
    with pytest.raises(CellCoercionError) as excinfo:
        parse_workbook(fixtures["malformed_currency"], schema)
    finding = excinfo.value.finding
    assert finding.rule_id == "ING-004"
    assert finding.column == "Monthly budget"
    assert finding.row is not None
    assert "twenty thousand" in finding.message


def test_malformed_registry_type_fails_explicitly(
    fixtures: dict[str, Path], schema: WorkbookSchema
) -> None:
    with pytest.raises(UnknownRegistryTypeError) as excinfo:
        parse_workbook(fixtures["malformed_keyword_row"], schema)
    assert excinfo.value.finding.rule_id == "ING-006"
    assert "Kyeword" in str(excinfo.value)


# ---------------------------------------------------------- acceptance condition


def _without_rows(bundle: WorkbookBundle) -> dict[str, object]:
    """Model dumps with row numbers removed — the one field shifting rows must change."""
    dumped = bundle.model_dump(
        exclude={"source_path", "source_sha256", "source_mtime", "findings", "panels"}
    )

    def strip(value: object) -> object:
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items() if key != "row"}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    return strip(dumped)  # type: ignore[return-value]


def test_shifted_rows_produce_identical_typed_objects(
    fixtures: dict[str, Path], schema: WorkbookSchema
) -> None:
    """The Phase 1B acceptance condition (spec test 9).

    Three blank rows inserted above every section. If any lookup used a row index, this
    fails. Row numbers themselves legitimately differ and are excluded.
    """
    clean = parse_workbook(fixtures["clean"], schema)
    shifted = parse_workbook(fixtures["shifted"], schema)

    assert _without_rows(clean) == _without_rows(shifted)
    assert [record.row for record in clean.campaigns] != [
        record.row for record in shifted.campaigns
    ]
