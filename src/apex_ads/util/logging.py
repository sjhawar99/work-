"""Logging: JSON lines to `logs/<run_id>.log`, concise human text to stderr.

Every record carries `run_id`. Nothing written here may contain PII — search-term text
belongs in the analysis CSVs, never in a log line (spec §16.1).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from apex_ads.util.redact import redact

LOGGER_NAME = "apex_ads"


class JsonLinesFormatter(logging.Formatter):
    """One JSON object per line, with the run ID and redacted message text."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "run_id": self.run_id,
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if record.exc_info:
            payload["traceback"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """Short text for a terminal, redacted like everything else."""

    def format(self, record: logging.LogRecord) -> str:
        return f"{record.levelname.lower():<8} {redact(record.getMessage())}"


def setup_logging(
    run_id: str, *, verbose: bool = False, log_dir: Path | None = None
) -> logging.Logger:
    """Configure and return the package logger. Safe to call more than once."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(HumanFormatter())
    stream.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(stream)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / f"{run_id}.log", encoding="utf-8")
        file_handler.setFormatter(JsonLinesFormatter(run_id))
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """The package logger, configured or not."""
    return logging.getLogger(LOGGER_NAME)
