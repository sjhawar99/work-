"""The Watchdog run: the sequence, the outputs and the manifest (spec §13).

    1. KEY        resolve the query-ID secret (created on first use)
    2. INGEST     read the export; the raw term boundary is crossed exactly here
    3. CLASSIFY   deterministic taxonomy match, `CLASSIFIER_UNRESOLVED` when unsure
    4. ROUTE      expected owner vs actual owner
    5. FIND       rank and surface; no threshold is invented
    6. OBSERVE    what approved negative policy did and did not prevent
                  (Stage 1 authors no policy — see `observations.py`)
    7. WRITE      staged into `<run_id>.partial/`, renamed on success

Staged like the compiler for the same reason: a half-written analysis directory that looks
complete is worse than none, because somebody will act on the part that got written.

The Watchdog **never** touches the account and never modifies the workbook. Its only
write outside `output/` is creating the query-ID key on first run.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from apex_ads import __version__
from apex_ads.compile_.build import SourceProvenance, source_provenance
from apex_ads.exit_codes import ExitCode
from apex_ads.models.config import Config
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.util.hashing import hash_tree, sha256_file
from apex_ads.util.queryid import QueryIdKey
from apex_ads.watchdog import (
    analysis_csv,
    dashboard,
    observations,
    present,
    report,
    taxonomy,
)
from apex_ads.watchdog.findings import Analysed, TermFinding, concentration, for_row
from apex_ads.watchdog.ingest import Export, choose_export, read_export, unkeyed_warning
from apex_ads.watchdog.routing import actual_key, coverage_for, positives, route

MANIFEST = "manifest.json"


@dataclass
class WatchdogResult:
    """Everything one Watchdog run produced."""

    directory: Path
    run_id: str
    export: Export
    analysed: list[Analysed] = field(default_factory=list)
    term_findings: list[TermFinding] = field(default_factory=list)
    observations: list[observations.Observation] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)

    @property
    def blockers(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity is Severity.BLOCKER]

    @property
    def exit_code(self) -> ExitCode:
        """`BLOCKER` when the run could not be trusted; otherwise OK.

        A Watchdog run with findings is a *successful* run — findings are the product. Only
        an unreadable export or an unkeyed identifier makes the run itself untrustworthy.
        """
        return ExitCode.BLOCKER if self.blockers else ExitCode.OK


def analyse(
    export: Export, bundle: WorkbookBundle, config: Config
) -> tuple[list[Analysed], list[TermFinding]]:
    """Classification, routing and findings for every readable row."""
    vocabulary = taxonomy.build(bundle, config.rules)
    keywords = positives(bundle)

    analysed: list[Analysed] = []
    for row in export.rows:
        classification = vocabulary.classify(row.term)
        served_by = actual_key(row.campaign, row.ad_group)
        coverage = coverage_for(row.term, row.keyword, row.match_type, served_by, keywords)
        routing = route(
            served_by,
            classification,
            coverage,
            vocabulary,
        )
        found = for_row(row, classification, routing, config.rules.watchdog)
        analysed.append(
            Analysed(
                row=row,
                classification=classification,
                routing=routing,
                findings=tuple(found),
            )
        )

    every: list[TermFinding] = [finding for item in analysed for finding in item.findings]
    every.extend(concentration(analysed, config.rules.watchdog, export.incomplete_campaigns()))
    return analysed, every


def execute(
    bundle: WorkbookBundle,
    config: Config,
    key: QueryIdKey,
    *,
    search_terms: Path,
    out_root: Path,
    run_id: str,
    today: date | None = None,
    propose_writeback: bool = False,
    write_dashboard: bool = True,
    source: SourceProvenance | None = None,
) -> WatchdogResult:
    """Run the Watchdog end to end, staging every file."""
    path = choose_export(search_terms)
    export = read_export(path, config.rules.watchdog, key, today=today)

    findings: list[Finding] = list(export.findings)
    unkeyed = unkeyed_warning(export.rows)
    if unkeyed is not None:
        findings.append(unkeyed)

    analysed, term_findings = analyse(export, bundle, config)
    seen = observations.build(
        analysed, taxonomy.build(bundle, config.rules), positives(bundle), config.rules
    )
    terms = [row.term for row in export.rows]

    staging = out_root / f"{run_id}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    files: list[Path] = []
    try:
        files.append(analysis_csv.write_analysis(staging, analysed))
        files.append(analysis_csv.write_observations(staging, seen, terms))
        files.append(analysis_csv.write_routing_issues(staging, analysed))
        files.append(analysis_csv.write_parse_errors(staging, export.parse_errors))
        files.append(
            report.write(
                staging,
                export,
                analysed,
                term_findings,
                seen,
                findings,
                config,
                terms,
                run_id=run_id,
                key_fingerprint=key.fingerprint,
            )
        )
        if write_dashboard:
            files.append(
                dashboard.write(staging, export, term_findings, seen, terms, run_id=run_id)
            )
        if propose_writeback:
            from apex_ads.watchdog import writeback

            files.extend(writeback.write(staging, seen, term_findings, run_id=run_id))

        provenance = source_provenance() if source is None else source
        manifest = _manifest(
            export,
            config,
            analysed,
            term_findings,
            seen,
            files,
            staging,
            run_id=run_id,
            key=key,
            source=provenance,
        )
        (staging / MANIFEST).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        final = out_root / run_id
        if final.exists():
            raise FileExistsError(f"refusing to overwrite an existing run at {final}")
        staging.rename(final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return WatchdogResult(
        directory=final,
        run_id=run_id,
        export=export,
        analysed=analysed,
        term_findings=term_findings,
        observations=seen,
        findings=findings,
        files=[final / item.name for item in files],
    )


def _manifest(
    export: Export,
    config: Config,
    analysed: list[Analysed],
    term_findings: list[TermFinding],
    observations_seen: list[observations.Observation],
    files: list[Path],
    directory: Path,
    *,
    run_id: str,
    key: QueryIdKey,
    source: SourceProvenance,
) -> dict[str, object]:
    """Traceability, with the key's fingerprint rather than the key.

    The fingerprint is what lets next week's reader know whether these query IDs join to
    this week's. It cannot be used to compute one.
    """
    return {
        "run_id": run_id,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool_version": __version__,
        "git_commit": source.commit,
        "source": source.as_dict(),
        "export": {
            "path": str(export.path),
            "name": export.path.name,
            "sha256": sha256_file(export.path),
            "rows": len(export.rows),
            "parse_errors": len(export.parse_errors),
            "spend_is_complete": export.spend_is_complete,
            # Three separate facts, kept separate. `covers` is the period this run describes
            # and carries the source of that claim; the other two are what it was derived
            # from. Collapsing them is what let the report, the dashboard and this file each
            # answer "what week is this?" differently.
            "covers": present.window(export).as_dict(),
            "declared_range": (
                {"first": str(export.declared_range[0]), "last": str(export.declared_range[1])}
                if export.declared_range
                else None
            ),
            "activity_range": present.activity_window(export).as_dict(),
        },
        "query_ids": {
            "keyed": True,
            "key_fingerprint": key.fingerprint,
            "note": "IDs join across runs only while the same key is used.",
        },
        "config_sha256": config.hashes,
        "thresholds": {
            name: (None if value is None else str(value))
            for name, value in config.rules.watchdog.thresholds.model_dump().items()
        },
        "counts": {
            "analysed": len(analysed),
            "findings": len(term_findings),
            "intentional_non_reach": sum(
                1 for item in observations_seen if item.kind == observations.INTENTIONAL_NON_REACH
            ),
            "observed_despite_negative": sum(
                1
                for item in observations_seen
                if item.kind == observations.OBSERVED_DESPITE_NEGATIVE
            ),
        },
        "files": hash_tree(directory, exclude=MANIFEST),
    }
