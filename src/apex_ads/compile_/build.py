"""The build compiler: the sequence, the three outcomes, and the staged write (spec §10).

    1. INGEST     read the workbook, record its hash
    2. VALIDATE   run every rule
    3. GATE       any BLOCKER → write the report, produce no CSVs
    4. TRANSFORM  normalise, dedupe, force PAUSED, order deterministically
    5. EXPORT     write the Editor files and MANUAL_STEPS.md
    6. REPORT     write the report and the manifest

Steps 1 to 3 complete before a single byte is written into the output directory.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from apex_ads.compile_ import manual_steps
from apex_ads.compile_.editor_export import WrittenFile, write_all
from apex_ads.compile_.transform import CompiledAccount, transform
from apex_ads.exit_codes import ExitCode
from apex_ads.ingest.urlcheck import UrlResult
from apex_ads.models.config import Config
from apex_ads.models.findings import Finding
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.util.hashing import sha256_file
from apex_ads.validate.runner import ValidationResult

DO_NOT_IMPORT = "DO_NOT_IMPORT.txt"
LATEST = "latest"

DRAFT_NOTICE = """DO NOT IMPORT THESE FILES.

This build is a DRAFT. Validation found no blockers, but one or more landing pages could
not be verified, so the destinations these ads point at are UNKNOWN — not confirmed
working.

An UNKNOWN destination is not a passing check. Google disapproves ads whose destination
it cannot reach, and a build that was never verified may be dead on arrival.

To get a deployable build, run again with network access so every landing page is
checked, and fix anything that fails.
"""


class Outcome(str, Enum):
    """What a build run produced."""

    READY = "READY"
    DRAFT = "DRAFT"
    FAILED = "FAILED"

    @property
    def exit_code(self) -> ExitCode:
        return {
            Outcome.READY: ExitCode.OK,
            Outcome.DRAFT: ExitCode.DRAFT,
            Outcome.FAILED: ExitCode.BLOCKER,
        }[self]


@dataclass
class BuildResult:
    """Everything one build run produced, and where it put it."""

    outcome: Outcome
    directory: Path
    run_id: str
    files: list[WrittenFile]
    findings: list[Finding]

    @property
    def deployable(self) -> bool:
        return self.outcome is Outcome.READY


def decide(result: ValidationResult, url_results: dict[str, UrlResult]) -> Outcome:
    """Blockers beat everything; an unverified destination prevents READY (Decision A6)."""
    if not result.passed:
        return Outcome.FAILED
    if any(check.status == "UNKNOWN" for check in url_results.values()):
        return Outcome.DRAFT
    return Outcome.READY


def _manifest(
    bundle: WorkbookBundle,
    config: Config,
    account: CompiledAccount,
    result: ValidationResult,
    files: list[WrittenFile],
    *,
    run_id: str,
    outcome: Outcome,
    url_results: dict[str, UrlResult],
) -> dict[str, object]:
    """Traceability: which workbook, which rules, which outputs (spec §10.6)."""
    return {
        "run_id": run_id,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outcome": outcome.value,
        "workbook": {
            "path": str(bundle.source_path),
            "sha256": bundle.source_sha256,
            "mtime": bundle.source_mtime.isoformat(timespec="seconds"),
        },
        "config_sha256": config.hashes,
        "counts": account.counts(),
        "findings": result.counts(),
        "url_checks": {
            path: {"status": check.status, "reason": check.reason}
            for path, check in url_results.items()
        },
        "files": [
            {"name": item.path.name, "rows": item.rows, "sha256": sha256_file(item.path)}
            for item in files
        ],
    }


def run_build(
    bundle: WorkbookBundle,
    config: Config,
    result: ValidationResult,
    url_results: dict[str, UrlResult],
    *,
    out_root: Path,
    run_id: str,
    write_report: Callable[[Path, Outcome], None],
) -> BuildResult:
    """Compile and write, staging everything so a partial run is never visible.

    Files go to `<run_id>.partial/`, which is renamed on success and deleted on failure.
    """
    outcome = decide(result, url_results)
    staging = out_root / f"{run_id}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    files: list[WrittenFile] = []
    findings: list[Finding] = []

    try:
        if outcome is not Outcome.FAILED:
            account = transform(bundle, config.rules)
            findings.extend(account.findings)
            files, unmapped = write_all(staging, account, config.editor_schema)
            findings.extend(unmapped)

            if unmapped:
                # A field nobody classified is a field that silently goes missing.
                outcome = Outcome.FAILED
                for item in files:
                    item.path.unlink(missing_ok=True)
                files = []
            else:
                manual_steps.write(staging, bundle, account, config, run_id=run_id)
                if outcome is Outcome.DRAFT:
                    (staging / DO_NOT_IMPORT).write_text(DRAFT_NOTICE, encoding="utf-8")

                manifest = _manifest(
                    bundle,
                    config,
                    account,
                    result,
                    files,
                    run_id=run_id,
                    outcome=outcome,
                    url_results=url_results,
                )
                (staging / "manifest.json").write_text(
                    json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
                )

        write_report(staging, outcome)

        suffix = ".DRAFT" if outcome is Outcome.DRAFT else ""
        final = out_root / f"{run_id}{suffix}"
        if final.exists():
            shutil.rmtree(final)
        staging.rename(final)
    except Exception:
        # A half-written export is worse than no export.
        shutil.rmtree(staging, ignore_errors=True)
        raise

    if outcome is Outcome.READY:
        _point_latest(out_root, final)

    return BuildResult(
        outcome=outcome,
        directory=final,
        run_id=run_id,
        files=[WrittenFile(path=final / item.path.name, rows=item.rows) for item in files],
        findings=findings,
    )


def _point_latest(out_root: Path, target: Path) -> None:
    """`latest` follows READY builds only. A DRAFT is invisible to anything following it."""
    pointer = out_root / LATEST
    try:
        if pointer.is_symlink() or pointer.exists():
            pointer.unlink()
        pointer.symlink_to(target.name)
    except OSError:
        # Windows without developer mode: leave a text pointer instead of failing a build.
        pointer.with_suffix(".txt").write_text(target.name, encoding="utf-8")
