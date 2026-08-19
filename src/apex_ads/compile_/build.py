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
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from apex_ads import __version__
from apex_ads.compile_ import manual_steps
from apex_ads.compile_.editor_export import WrittenFile, write_all
from apex_ads.compile_.routing import check_routes
from apex_ads.compile_.transform import CompiledAccount, transform
from apex_ads.exit_codes import ExitCode
from apex_ads.ingest.urlcheck import UrlResult
from apex_ads.models.config import Config
from apex_ads.models.findings import Finding
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.util.hashing import sha256_file
from apex_ads.util.redact import redact
from apex_ads.validate.runner import ValidationResult

DO_NOT_IMPORT = "DO_NOT_IMPORT.txt"
MANIFEST = "manifest.json"
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

DRAFT_REASON_SOURCE = """
* SOURCE NOT REPRODUCIBLE
  These files were built from a working copy with uncommitted changes, or from a checkout
  whose commit could not be read. The manifest cannot name code that anybody could check
  out and run again, so nobody can prove later what produced this import.

  To clear this: commit (or stash) every change and run the build again from a clean
  checkout.
"""

DRAFT_NOTICE_FOOTER = """
Until every item above is cleared, no build can be READY. That is deliberate: READY has
to mean import-ready, not "the compiler's own logic passed".
"""


def draft_notice(*, schema_verified: bool, unknown_urls: int, source_known: bool = True) -> str:
    """The quarantine notice, naming every reason this build is not deployable."""
    parts = [DRAFT_NOTICE_HEADER]
    if not schema_verified:
        parts.append(DRAFT_REASON_SCHEMA)
    if not source_known:
        parts.append(DRAFT_REASON_SOURCE)
    if unknown_urls:
        parts.append(DRAFT_REASON_URLS)
    parts.append(DRAFT_NOTICE_FOOTER)
    return "".join(parts)


class RunDirectoryExistsError(Exception):
    """A completed run already occupies the target directory. It is never overwritten."""


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
    source_known: bool = True,
) -> Outcome:
    """What this run may produce.

    `READY` means **import-ready**, not "the compiler's own logic passed". Three separate
    things can withhold it, and each is an external contract this tool cannot verify for
    itself:

    * a BLOCKER — the workbook is wrong;
    * an unverified destination — the ads may point at a page that does not load;
    * an unverified Editor schema — Google may not understand the files at all;
    * an unknown or modified source tree — nobody can reproduce what built these files.

    The last two are the ones most easily rationalised away. A build whose column names
    were guessed is not ready; it is a plausible draft. A build from a working copy with
    uncommitted edits records a commit whose code never ran.
    """
    if not result.passed:
        return Outcome.FAILED
    if not editor_schema_verified:
        return Outcome.DRAFT
    if not source_known:
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
    directory: Path,
    *,
    run_id: str,
    outcome: Outcome,
    url_results: dict[str, UrlResult],
    source: SourceProvenance,
) -> dict[str, object]:
    """Traceability: which workbook, which rules, which outputs (spec §10.6)."""
    return {
        "run_id": run_id,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool_version": __version__,
        "git_commit": source.commit,
        "source": source.as_dict(),
        "outcome": outcome.value,
        "editor_schema_verified": config.editor_schema.verified,
        "verified_against": config.editor_schema.verified_against.model_dump(),
        "workbook": {
            "path": str(bundle.source_path),
            "sha256": bundle.source_sha256,
            "mtime": bundle.source_mtime.isoformat(timespec="seconds"),
        },
        "config": {
            name: {"path": str(path), "sha256": config.hashes[name]}
            for name, path in config.sources.items()
        },
        "config_sha256": config.hashes,
        "counts": account.counts(),
        "call_assets": {
            str(resolved.key): {
                "number": redact(resolved.number),
                "schedule": resolved.schedule,
                "source": resolved.source,
            }
            for resolved in account.call_assets
        },
        "findings": result.counts(),
        "url_checks": {
            path: {"status": check.status, "reason": check.reason}
            for path, check in url_results.items()
        },
        "files": [
            {"name": item.path.name, "rows": item.rows, "sha256": sha256_file(item.path)}
            for item in files
        ],
        "artifacts": _artifact_hashes(directory),
    }


def _artifact_hashes(directory: Path) -> list[dict[str, object]]:
    """Hash **every** file in the run, not only the CSVs.

    MANUAL_STEPS.md, the pre-flight report and DO_NOT_IMPORT.txt are deployment artifacts:
    a human acts on them. Hashing only the CSVs made "what exactly did we import, and
    under what instructions" half-answerable.
    """
    return [
        {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(directory.iterdir())
        if path.is_file() and path.name != MANIFEST
    ]


UNKNOWN_COMMIT = "unknown"


@dataclass(frozen=True)
class SourceProvenance:
    """Which source produced this build, and whether that source is recoverable."""

    commit: str
    dirty: bool

    @property
    def known(self) -> bool:
        """True when the exact code that built this can be checked out again."""
        return self.commit != UNKNOWN_COMMIT and not self.dirty

    def as_dict(self) -> dict[str, object]:
        return {"commit": self.commit, "dirty": self.dirty, "known": self.known}


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def source_provenance() -> SourceProvenance:
    """The commit this build came from, and whether the tree had uncommitted changes.

    Recording only the commit was half an answer. `git_commit: "abc123"` from a tree with
    edited validators names a commit whose code never ran, and `"unknown"` names nothing
    at all — both pass a test that merely asserts the key is present. A deployable build
    has to be reproducible from source, so an unknown or dirty tree withholds READY the
    same way an unverified Editor schema does.
    """
    head = _git("rev-parse", "HEAD")
    if head is None or not head.strip():
        return SourceProvenance(commit=UNKNOWN_COMMIT, dirty=True)
    status = _git("status", "--porcelain")
    if status is None:
        return SourceProvenance(commit=head.strip(), dirty=True)
    return SourceProvenance(commit=head.strip(), dirty=bool(status.strip()))


def run_build(
    bundle: WorkbookBundle,
    config: Config,
    result: ValidationResult,
    url_results: dict[str, UrlResult],
    *,
    out_root: Path,
    run_id: str,
    write_report: Callable[[Path, Outcome, list[Finding]], None],
    source: SourceProvenance | None = None,
) -> BuildResult:
    """Compile and write, staging everything so a partial run is never visible.

    Files go to `<run_id>.partial/`, which is renamed on success and deleted on failure.

    `write_report` is handed the compile-stage findings as well as the outcome. It has to
    be: `EXP-001` and `EXP-002` are discovered *here*, after validation has finished, and
    they are the two findings most likely to fail a build. Reporting only the validator's
    findings produced the worst possible pairing — exit 2, and a pre-flight report with
    nothing in it that explained why.
    """
    source = source_provenance() if source is None else source
    outcome = decide(
        result,
        url_results,
        editor_schema_verified=config.editor_schema.verified,
        source_known=source.known,
    )
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

            # Route integrity first: check every record type has a destination that can
            # carry it before writing anything, so a mis-routed type cannot leave a
            # half-populated directory behind.
            misrouted = check_routes(account, config.editor_schema)
            findings.extend(misrouted)

            files, unmapped = write_all(staging, account, config.editor_schema)
            findings.extend(unmapped)

            if unmapped or misrouted:
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
                            source_known=source.known,
                        ),
                        encoding="utf-8",
                    )

        write_report(staging, outcome, findings)

        if outcome is not Outcome.FAILED and not unmapped and not misrouted:
            # Written last, so it can hash the report and MANUAL_STEPS.md alongside the
            # CSVs: every artifact a human acts on is covered, not just the importable
            # ones.
            manifest = _manifest(
                bundle,
                config,
                account,
                result,
                files,
                staging,
                run_id=run_id,
                outcome=outcome,
                url_results=url_results,
                source=source,
            )
            (staging / MANIFEST).write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        suffix = ".DRAFT" if outcome is Outcome.DRAFT else ""
        final = out_root / f"{run_id}{suffix}"
        if final.exists():
            # A completed run is evidence. Never delete one to make room — that was the
            # overwrite mechanism sitting directly beneath the comment promising no run
            # ever overwrites another.
            raise RunDirectoryExistsError(
                f"refusing to overwrite an existing run at {final}. Run IDs are unique; "
                "if this happened, something is reusing one."
            )
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
