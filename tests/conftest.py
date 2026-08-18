"""Shared fixtures. Tests read `tests/fixtures/` only — never `input/` (spec §16.3)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "fixtures"))

from build_fixtures import build_all  # noqa: E402

from apex_ads.models.config import WorkbookSchema, load_config  # noqa: E402


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
