"""Shared fixtures. Tests read `tests/fixtures/` only — never `input/` (spec §16.3)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "fixtures"))

from build_fixtures import build_all  # noqa: E402

from apex_ads.models.config import Config, Rules, WorkbookSchema, load_config  # noqa: E402


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def config_dir(repo_root: Path) -> Path:
    return repo_root / "config"


@pytest.fixture(scope="session")
def schema(config_dir: Path) -> WorkbookSchema:
    return load_config(config_dir).workbook_schema


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Every synthetic workbook, built fresh. Nothing binary is committed."""
    return build_all(tmp_path_factory.mktemp("workbooks"))


@pytest.fixture(scope="session")
def real_workbook(repo_root: Path) -> Path:
    """The real export, when a developer has one locally. Never committed."""
    path = repo_root / "input" / "workbook.xlsx"
    if not path.is_file():
        pytest.skip("input/workbook.xlsx not present (expected in CI)")
    return path


@pytest.fixture(scope="session")
def config(config_dir: Path) -> Config:
    return load_config(config_dir)


def retarget(rules: Rules) -> Rules:
    """The real rules, pointed at the synthetic fixtures.

    The fixtures are a two-campaign, three-ad-group miniature of the real account, so the
    Stage-1 invariants are restated at fixture scale. Every *rule* under test is the real
    one; only the numbers it is pointed at change.
    """
    rules = rules.model_copy(deep=True)
    account = rules.account.model_copy(
        update={
            "monthly_budget": Decimal("25000"),
            "expected_campaign_count": 2,
            "expected_ad_group_count": 3,
        }
    )
    negatives = rules.negatives.model_copy(
        update={
            "campaign_scope_aliases": {
                "Brand": ["TST | Search | Brand | Jaipur"],
                "Neuro": ["TST | Search | Neuro | Jaipur"],
            },
            # Only the list the fixture workbook actually uses. NEG-008 compares all
            # three routing sources including empty ones, so a list declared in config
            # but absent from the fixture's registry and routing is a real disagreement
            # — the fixture has to be internally consistent, not merely convenient.
            "shared_lists": {
                "ROUTE_BRAND": rules.negatives.shared_lists["ROUTE_BRAND"].model_copy(
                    update={"applies_to": ["TST | Search | Neuro | Jaipur"]}
                )
            },
        }
    )
    return rules.model_copy(update={"account": account, "negatives": negatives})


@pytest.fixture(scope="session")
def fixture_rules(config: Config) -> Rules:
    """The real rules at fixture scale — see `retarget`."""
    return retarget(config.rules)


@pytest.fixture(scope="session")
def fixture_config_dir(tmp_path_factory: pytest.TempPathFactory, config: Config) -> Path:
    """A real `config/` directory retargeted at the fixtures, for CLI-level tests.

    The CLI loads config from disk, so a subprocess test cannot use the `fixture_rules`
    object. This materialises the same rules as YAML, so `apex build` on a fixture reaches
    the compile stage instead of stopping at "this is not a ₹62,000 five-campaign account".
    """
    import shutil

    import yaml

    directory = tmp_path_factory.mktemp("config")
    shutil.rmtree(directory)
    shutil.copytree(REPO_ROOT / "config", directory)
    rules = retarget(config.rules)
    (directory / "rules.yaml").write_text(
        yaml.safe_dump(
            yaml.safe_load(rules.model_dump_json()), sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    return directory
