from __future__ import annotations

import json
import logging
from pathlib import Path

from apex_ads.util.logging import get_logger, setup_logging


def test_json_lines_written_with_run_id(tmp_path: Path) -> None:
    logger = setup_logging("20260818-120000-deadbeef", log_dir=tmp_path)
    logger.info("parsed 112 positive keywords")
    for handler in logger.handlers:
        handler.flush()

    lines = (tmp_path / "20260818-120000-deadbeef.log").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    assert record["run_id"] == "20260818-120000-deadbeef"
    assert record["level"] == "INFO"
    assert record["message"] == "parsed 112 positive keywords"


def test_log_output_is_redacted(tmp_path: Path) -> None:
    """Guardrail §18.11: a log line may never carry PII, even if a caller passes it."""
    logger = setup_logging("run", log_dir=tmp_path)
    logger.warning("unparsed query: call 9876543210 or mail a@b.com")
    for handler in logger.handlers:
        handler.flush()

    written = (tmp_path / "run.log").read_text(encoding="utf-8")
    assert "9876543210" not in written
    assert "a@b.com" not in written
    assert "[phone]" in written and "[email]" in written


def test_setup_is_idempotent(tmp_path: Path) -> None:
    setup_logging("run", log_dir=tmp_path)
    logger = setup_logging("run", log_dir=tmp_path)
    assert len(logger.handlers) == 2


def test_verbose_sets_debug_level(tmp_path: Path) -> None:
    logger = setup_logging("run", verbose=True, log_dir=tmp_path)
    assert logger.level == logging.DEBUG
    assert get_logger() is logger
