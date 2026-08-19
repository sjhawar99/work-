from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from apex_ads.models.config import Config, ConfigError, load_config


def test_real_config_loads(config_dir: Path) -> None:
    config = load_config(config_dir)
    assert config.rules.version >= 1
    assert set(config.hashes) == {"rules", "workbook_schema", "editor_schema"}


def test_stage_one_invariants(config_dir: Path) -> None:
    account = load_config(config_dir).rules.account
    assert account.monthly_budget == Decimal("62000")
    assert account.monthly_budget_tolerance == Decimal("0")
    assert account.expected_campaign_count == 5
    assert account.expected_ad_group_count == 9


def test_broad_is_not_an_allowed_positive_match_type(config_dir: Path) -> None:
    keywords = load_config(config_dir).rules.keywords
    assert "BROAD" not in keywords.allowed_positive_match_types
    assert "BROAD" in keywords.allowed_negative_match_types


def test_watchdog_thresholds_are_null_in_stage_one(config_dir: Path) -> None:
    """Decision C3: no invented cutoffs. `None` means "we have no data yet"."""
    watchdog = load_config(config_dir).rules.watchdog
    assert watchdog.thresholds.junk_min_impressions is None
    assert watchdog.thresholds.junk_max_ctr is None
    assert watchdog.thresholds.concentration_spend_share is None
    assert watchdog.thresholds.explicit_keyword_gap_min_conversions is None
    assert watchdog.concentration_mode == "rank_and_review"


def test_shared_lists_apply_to_the_four_non_brand_campaigns(config_dir: Path) -> None:
    shared = load_config(config_dir).rules.negatives.shared_lists
    assert set(shared) == {
        "ROUTE_BRAND",
        "ROUTE_COMPETITORS",
        "STAGE1_HOLD_COMPARISON",
        "STAGE1_HOLD_ACTION",
        "STAGE1_HOLD_URGENCY",
    }
    for name, entry in shared.items():
        assert len(entry.applies_to) == 4, name
        assert not any("Brand" in campaign for campaign in entry.applies_to), name


def test_workbook_is_a_google_sheet_export(config_dir: Path) -> None:
    workbook = load_config(config_dir).rules.workbook
    assert workbook.source == "google_sheet_export"
    assert workbook.canonical_source_is_google_sheet is True
    assert workbook.export_is_read_only_artifact is True
    assert workbook.staleness_check_is_advisory_only is True


def test_schema_declares_exactly_four_sheets(config_dir: Path) -> None:
    sheets = load_config(config_dir).workbook_schema.sheets
    assert set(sheets.values()) == {"01 ACTIONS", "02 BUILD", "03 KEYWORDS", "04 DAILY"}


def test_editor_schema_preserves_all_four_negative_scopes(config_dir: Path) -> None:
    artifacts = load_config(config_dir).editor_schema.negative_artifacts
    assert {artifact.level for artifact in artifacts.values()} == {
        "ACCOUNT",
        "SHARED_LIST",
        "CAMPAIGN",
        "AD_GROUP",
    }


def test_missing_directory_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    assert "rules.yaml" in str(excinfo.value)


def test_missing_key_is_named(config_dir: Path, tmp_path: Path) -> None:
    for name in ("rules.yaml", "workbook_schema.yaml", "editor_schema.yaml"):
        (tmp_path / name).write_text((config_dir / name).read_text(), encoding="utf-8")
    rules = yaml.safe_load((tmp_path / "rules.yaml").read_text())
    del rules["account"]["monthly_budget"]
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    assert "account.monthly_budget" in str(excinfo.value)


def test_unknown_key_is_rejected(config_dir: Path, tmp_path: Path) -> None:
    """A typo must fail loudly rather than silently disabling a rule."""
    for name in ("rules.yaml", "workbook_schema.yaml", "editor_schema.yaml"):
        (tmp_path / name).write_text((config_dir / name).read_text(), encoding="utf-8")
    rules = yaml.safe_load((tmp_path / "rules.yaml").read_text())
    rules["account"]["monthly_budgett"] = 62000
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    assert "monthly_budgett" in str(excinfo.value)


def test_config_that_permits_broad_positives_will_not_load(
    config_dir: Path, tmp_path: Path
) -> None:
    """Guardrail §18.5 is enforced at load time, not only at build time."""
    for name in ("rules.yaml", "workbook_schema.yaml", "editor_schema.yaml"):
        (tmp_path / name).write_text((config_dir / name).read_text(), encoding="utf-8")
    rules = yaml.safe_load((tmp_path / "rules.yaml").read_text())
    rules["keywords"]["allowed_positive_match_types"].append("BROAD")
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    assert "BROAD" in str(excinfo.value)


def test_invalid_yaml_names_the_file(tmp_path: Path) -> None:
    (tmp_path / "rules.yaml").write_text("account: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    assert "invalid YAML" in str(excinfo.value)


def test_xlsx_native_is_rejected(config_dir: Path, tmp_path: Path) -> None:
    """Decision D3: one production source mode. The Google Sheet is canonical."""
    for name in ("rules.yaml", "workbook_schema.yaml", "editor_schema.yaml"):
        (tmp_path / name).write_text((config_dir / name).read_text(), encoding="utf-8")
    rules = yaml.safe_load((tmp_path / "rules.yaml").read_text())
    rules["workbook"]["source"] = "xlsx_native"
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    assert "workbook.source" in str(excinfo.value)


# ------------------------------------------------ a list name belongs to one level


def test_a_list_name_in_two_levels_will_not_load(config: Config) -> None:
    """`NEG-008` answers "which level owns this list?" — the answer has to be single.

    An overlapping name makes the routing check compare the wrong sources depending on
    which branch happens to run first, and nothing anywhere reports that it did.
    """
    negatives = config.rules.negatives
    with pytest.raises(ValidationError) as caught:
        type(negatives).model_validate(
            {
                **negatives.model_dump(),
                "campaign_sets": [*negatives.campaign_sets, negatives.account_lists[0]],
            }
        )
    assert "exactly one level" in str(caught.value)
    assert negatives.account_lists[0] in str(caught.value)


def test_a_repeated_list_name_within_one_level_will_not_load(config: Config) -> None:
    negatives = config.rules.negatives
    with pytest.raises(ValidationError) as caught:
        type(negatives).model_validate(
            {
                **negatives.model_dump(),
                "account_lists": [*negatives.account_lists, negatives.account_lists[0]],
            }
        )
    assert "repeats" in str(caught.value)


def test_the_shipped_config_keeps_its_levels_disjoint(config: Config) -> None:
    """Not only enforceable — enforced on the config this repo actually ships."""
    negatives = config.rules.negatives
    groups = [
        set(negatives.account_lists),
        set(negatives.shared_lists),
        set(negatives.campaign_sets),
        set(negatives.ad_group_sets),
    ]
    for index, first in enumerate(groups):
        for second in groups[index + 1 :]:
            assert not first & second
