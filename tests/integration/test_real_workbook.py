"""Reconciliation against the real export.

Skipped when `input/workbook.xlsx` is absent — which is the normal case in CI, because
the real workbook is client data and is never committed. When a developer does have the
export locally, these assertions are the proof that `workbook_schema.yaml` still matches
the file it was written from (the PRE-PHASE reconnaissance).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import WorkbookSchema
from apex_ads.util.hashing import sha256_file

EXPECTED = {
    "blocking_actions": 8,
    "running_actions": 17,
    "campaigns": 5,
    "ad_groups": 9,
    "landing_pages": 9,
    "supporting_assets": 12,
    "measurement_contract": 10,
    "ads": 9,
    "keywords": 112,
    "negatives": 226,
}


def test_every_section_matches_the_reconnaissance(
    real_workbook: Path, schema: WorkbookSchema
) -> None:
    bundle = parse_workbook(real_workbook, schema)
    actual = {name: len(getattr(bundle, name)) for name in EXPECTED}
    assert actual == EXPECTED


def test_budgets_sum_to_the_declared_total(real_workbook: Path, schema: WorkbookSchema) -> None:
    bundle = parse_workbook(real_workbook, schema)
    total = sum(campaign.monthly_budget for campaign in bundle.campaigns)
    assert total == Decimal("62000")
    assert bundle.declared_monthly_total == total


def test_scope_levels_present_in_the_real_registry(
    real_workbook: Path, schema: WorkbookSchema
) -> None:
    bundle = parse_workbook(real_workbook, schema)
    levels = {negative.scope.level for negative in bundle.negatives}
    assert levels == {"ACCOUNT", "SHARED_LIST", "CAMPAIGN", "AD_GROUP"}

    shared = {
        tuple(negative.scope.applied_campaigns)
        for negative in bundle.negatives
        if negative.scope.level == "SHARED_LIST"
    }
    assert shared == {("Neuro", "Generic", "Ortho", "Nephro")}


def test_no_broad_positive_keywords_in_the_real_workbook(
    real_workbook: Path, schema: WorkbookSchema
) -> None:
    bundle = parse_workbook(real_workbook, schema)
    assert not [keyword for keyword in bundle.keywords if keyword.match_type == "BROAD"]
    assert [n for n in bundle.negatives if n.match_type == "BROAD"]


def test_derived_copy_paste_values_all_agree(real_workbook: Path, schema: WorkbookSchema) -> None:
    bundle = parse_workbook(real_workbook, schema)
    mismatched = [row for row in bundle.keywords + bundle.negatives if not row.copy_paste_matches]
    assert not mismatched


def test_every_rsa_has_twelve_headlines_and_four_descriptions(
    real_workbook: Path, schema: WorkbookSchema
) -> None:
    bundle = parse_workbook(real_workbook, schema)
    assert {len(ad.headlines) for ad in bundle.ads} == {12}
    assert {len(ad.descriptions) for ad in bundle.ads} == {4}


def test_parsing_never_modifies_the_export(real_workbook: Path, schema: WorkbookSchema) -> None:
    """The Google Sheet is canonical; the export is read-only (AGENTS.md rule 6)."""
    before = sha256_file(real_workbook)
    parse_workbook(real_workbook, schema)
    assert sha256_file(real_workbook) == before
