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

DRAFT_NOTICE_HEADER = """DO NOT IMPORT THESE FILES.

This build is a DRAFT. Validation found no blockers, but at least one external contract
this tool cannot verify for itself is still open:
"""

DRAFT_REASON_URLS = """
* LANDING PAGES UNVERIFIED
  One or more destinations could not be checked, so the pages these ads point at are
  UNKNOWN - not confirmed working. Google disapproves ads whose destination it cannot
  reach. Run again with network access and fix anything that fails.
"""

DRAFT_REASON_SCHEMA = """
* EDITOR COLUMN NAMES UNVERIFIED
  The column headers in these files were written from knowledge of Google Ads Editor,
  not reconciled against an export of this account. Editor matches on recognisable
  English headers, so a wrong one means a failed or partial import - the one contract
  that decides whether Google understands these files at all.

  To clear this: export the account from Google Ads Editor, reconcile every header in
  config/editor_schema.yaml against that export, then set `verified: true` and record
  the export date, Editor version and file hash in `verified_against`.
"""

DRAFT_NOTICE_FOOTER = """
Until every item above is cleared, no build can be READY. That is deliberate: READY has
to mean import-ready, not "the compiler's own logic passed".
"""


def draft_notice(*, schema_verified: bool, unknown_urls: int) -> str:
    """The quarantine notice, naming every reason this build is not deployable."""
    parts = [DRAFT_NOTICE_HEADER]
    if not schema_verified:
        parts.append(DRAFT_REASON_SCHEMA)
    if unknown_urls:
        parts.append(DRAFT_REASON_URLS)
    parts.append(DRAFT_NOTICE_FOOTER)
    return "".join(parts)


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


def decide(
    result: ValidationResult,
    url_results: dict[str, UrlResult],
    *,
    editor_schema_verified: bool,
) -> Outcome:
    """What this run may produce.

    `READY` means **import-ready**, not "the compiler's own logic passed". Three separate
    things can withhold it, and each is an external contract this tool cannot verify for
    itself:

    * a BLOCKER — the workbook is wrong;
    * an unverified destination — the ads may point at a page that does not load;
    * an unverified Editor schema — Google may not understand the files at all.

    The last one is the newest and the most easily rationalised away. A build whose column
    names were guessed is not ready; it is a plausible draft.
    """
    if not result.passed:
        return Outcome.FAILED
    if not editor_schema_verified:
        return Outcome.DRAFT
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
        "editor_schema_verified": config.editor_schema.verified,
        "verified_against": config.editor_schema.verified_against.model_dump(),
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
    outcome = decide(result, url_results, editor_schema_verified=config.editor_schema.verified)
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
                    (staging / DO_NOT_IMPORT).write_text(
                        draft_notice(
                            schema_verified=config.editor_schema.verified,
                            unknown_urls=sum(
                                1 for c in url_results.values() if c.status == "UNKNOWN"
                            ),
                        ),
                        encoding="utf-8",
                    )

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
