"""Command line interface.

Phase 0 wires the argument surface and `apex version`. Every other subcommand exits with
`BAD_INVOCATION` and says it is not implemented — an honest stub beats a half-built one.

Note on argparse: its default exit code for a usage error is 2, which in this tool means
"validation BLOCKER". `Parser` overrides that to `BAD_INVOCATION` (5) so the exit-code
contract in spec §15.1 holds for bad invocations too.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from apex_ads import __version__
from apex_ads.compile_.build import Outcome, run_build
from apex_ads.exit_codes import ExitCode
from apex_ads.ingest.errors import WorkbookError
from apex_ads.ingest.urlcheck import UrlResult, check_all
from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import Config, ConfigError, load_config
from apex_ads.models.findings import Finding
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.report import preflight
from apex_ads.util.hashing import short_hash
from apex_ads.util.logging import setup_logging
from apex_ads.util.runid import make as make_run_id
from apex_ads.validate.registry import validators_for
from apex_ads.validate.runner import Mode, ValidationResult
from apex_ads.validate.runner import run as run_validators

DEFAULT_CONFIG_DIR = Path("config")
DEFAULT_WORKBOOK = Path("input/workbook.xlsx")

NOT_IMPLEMENTED = "not implemented yet — see CODEX_TASKS.md for the phase that adds it"


class Parser(argparse.ArgumentParser):
    """`argparse.ArgumentParser` that exits 5, not 2, on a usage error."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(ExitCode.BAD_INVOCATION)


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown" if result.returncode == 0 else "unknown"


def build_parser() -> Parser:
    """The full argument surface. No `--force`, and never will be (guardrail §18.4)."""
    parser = Parser(prog="apex", description="Apex Google Ads Operating System")
    parser.add_argument("--version", action="version", version=f"apex {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--config", type=Path, default=DEFAULT_CONFIG_DIR, help="config directory")
        sub.add_argument("--verbose", action="store_true", help="debug logging")

    workbook_help = "path to the workbook export (never edited; see AGENTS.md)"

    build = subcommands.add_parser("build", help="compile the workbook into Editor files")
    build.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK, help=workbook_help)
    build.add_argument("--out", type=Path, default=Path("output/build"))
    build.add_argument("--no-network", action="store_true", help="skip URL checks; forces a DRAFT")
    common(build)

    validate = subcommands.add_parser("validate", help="validate only; never writes CSVs")
    validate.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK, help=workbook_help)
    validate.add_argument("--no-network", action="store_true")
    validate.add_argument(
        "--out", type=Path, default=Path("output/validate"), help="where the report is written"
    )
    common(validate)

    watchdog = subcommands.add_parser("watchdog", help="weekly search-term analysis")
    watchdog.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK, help=workbook_help)
    watchdog.add_argument("--search-terms", type=Path, default=Path("input/search_terms/"))
    watchdog.add_argument("--propose-writeback", action="store_true")
    watchdog.add_argument("--dashboard", action="store_true")
    common(watchdog)

    drift = subcommands.add_parser("drift", help="compare the workbook against a live export")
    drift.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK, help=workbook_help)
    drift.add_argument("--live-export", type=Path, default=Path("input/live_export"))
    common(drift)

    version = subcommands.add_parser("version", help="tool version, git commit, config hashes")
    common(version)

    return parser


@dataclass(frozen=True)
class Prepared:
    """The shared front half of `validate` and `build`: parsed, checked, validated."""

    bundle: WorkbookBundle
    result: ValidationResult
    url_results: dict[str, UrlResult]
    run_id: str


def _load_and_check(args: argparse.Namespace, config: Config) -> Prepared | ExitCode:
    """Parse the workbook, check its destinations, and run every rule."""
    if not args.workbook.is_file():
        print(f"apex {args.command}: workbook not found: {args.workbook}", file=sys.stderr)
        return ExitCode.BAD_INVOCATION

    bundle = parse_workbook(args.workbook, config.workbook_schema)
    run_id = make_run_id(bundle.source_sha256)
    setup_logging(run_id, verbose=args.verbose, log_dir=Path("logs"))

    url_results = check_all(
        [page.planned_url for page in bundle.landing_pages],
        config.rules.landing_pages,
        network_enabled=not args.no_network,
    )
    mode: Mode = "build" if args.command == "build" else "validate"
    result = run_validators(bundle, config.rules, validators=validators_for(url_results), mode=mode)
    return Prepared(bundle=bundle, result=result, url_results=url_results, run_id=run_id)


def _run_build(args: argparse.Namespace, config: Config) -> ExitCode:
    """Compile the workbook into Google Ads Editor import files (spec §10)."""
    try:
        loaded = _load_and_check(args, config)
    except WorkbookError as exc:
        return _report_structural_failure(args, config, exc.finding)
    if isinstance(loaded, ExitCode):
        return loaded

    def write_report(directory: Path, outcome: Outcome) -> None:
        headline = f"BUILD {outcome.value}"
        if outcome is Outcome.DRAFT:
            # Name the reasons that actually apply. The headline used to announce
            # incomplete URL validation even when every destination passed and the
            # unverified Editor schema was the sole cause — a report that misstates why
            # it withheld a build teaches people to stop reading the reason.
            reasons: list[str] = []
            if not config.editor_schema.verified:
                reasons.append("EDITOR SCHEMA UNVERIFIED")
            unknown = sum(1 for c in loaded.url_results.values() if c.status == "UNKNOWN")
            if unknown:
                reasons.append(f"URL VALIDATION INCOMPLETE ({unknown} UNKNOWN)")
            headline += f" - {', '.join(reasons)} - NOT DEPLOYABLE"
        preflight.write(
            directory,
            loaded.bundle,
            loaded.result,
            run_id=loaded.run_id,
            config_hashes=config.hashes,
            url_results=loaded.url_results,
            url_checks=_url_summary(loaded.url_results, no_network=args.no_network),
            outcome=headline,
        )

    outcome = run_build(
        loaded.bundle,
        config,
        loaded.result,
        loaded.url_results,
        out_root=args.out,
        run_id=loaded.run_id,
        write_report=write_report,
    )

    report = outcome.directory / "PRE_FLIGHT_REPORT.txt"
    if report.is_file():
        print(report.read_text(encoding="utf-8"))

    print(f"BUILD {outcome.outcome.value}", file=sys.stderr)
    print(f"output: {outcome.directory}", file=sys.stderr)
    if outcome.outcome is Outcome.READY:
        for item in outcome.files:
            print(f"  {item.path.name:<28} {item.rows} row(s)", file=sys.stderr)
    elif outcome.outcome is Outcome.DRAFT:
        print(
            "  quarantined — see DO_NOT_IMPORT.txt. Nothing here may be imported.", file=sys.stderr
        )
    return outcome.outcome.exit_code


def _run_validate(args: argparse.Namespace, config: Config) -> ExitCode:
    """Validate the workbook and write a report. Never writes Editor CSVs (spec §15)."""
    if not args.workbook.is_file():
        print(f"apex validate: workbook not found: {args.workbook}", file=sys.stderr)
        return ExitCode.BAD_INVOCATION

    try:
        bundle = parse_workbook(args.workbook, config.workbook_schema)
    except WorkbookError as exc:
        return _report_structural_failure(args, config, exc.finding)

    run_id = make_run_id(bundle.source_sha256)
    setup_logging(run_id, verbose=args.verbose, log_dir=Path("logs"))

    url_results = check_all(
        [page.planned_url for page in bundle.landing_pages],
        config.rules.landing_pages,
        network_enabled=not args.no_network,
    )
    result = run_validators(bundle, config.rules, validators=validators_for(url_results))

    report = preflight.write(
        args.out / run_id,
        bundle,
        result,
        run_id=run_id,
        config_hashes=config.hashes,
        url_results=url_results,
        url_checks=_url_summary(url_results, no_network=args.no_network),
    )
    print(report.read_text(encoding="utf-8"))
    print(f"report written to {report}", file=sys.stderr)

    if not result.passed:
        return ExitCode.BLOCKER
    if any(check.status == "UNKNOWN" for check in url_results.values()):
        # No BLOCKERs, but destinations went unverified: not deployable (Decision A6).
        return ExitCode.DRAFT
    return ExitCode.OK


def _url_summary(results: dict[str, UrlResult], *, no_network: bool) -> str:
    """The report header line. Never says "passed" about a check that did not run."""
    if not results:
        return "NOT RUN — no landing pages declared"
    if no_network:
        return f"SKIPPED (--no-network) — {len(results)} destination(s) UNKNOWN, not verified"
    counts = {status: 0 for status in ("PASS", "BLOCKER", "UNKNOWN")}
    for check in results.values():
        counts[check.status] += 1
    return (
        f"RUN — {len(results)} destination(s): {counts['PASS']} OK, "
        f"{counts['BLOCKER']} unreachable, {counts['UNKNOWN']} UNKNOWN"
    )


def _report_structural_failure(
    args: argparse.Namespace, config: Config, finding: Finding
) -> ExitCode:
    """A workbook the parser cannot read is a BLOCKER, reported in the usual shape."""
    print("APEX GOOGLE ADS OS — PRE-FLIGHT REPORT")
    print(f"Workbook:   {args.workbook}")
    print()
    print("RESULT: VALIDATION FAILED — 1 BLOCKER, 0 WARNINGS")
    print()
    print("BLOCKERS")
    location = finding.sheet + (f" r{finding.row}" if finding.row is not None else "")
    print(f"  [{finding.rule_id}] {location:<16} {finding.message}")
    if finding.remedy:
        print(f"            Fix: {finding.remedy}")
    print()
    print("NO DEPLOYABLE FILES GENERATED")
    return ExitCode.BLOCKER


def _run_version_with(args: argparse.Namespace, config: Config) -> ExitCode:
    print(f"apex {__version__}")
    print(f"python       {sys.version.split()[0]}")
    print(f"git commit   {_git_commit()}")
    print(f"config dir   {args.config}")
    for name in sorted(config.hashes):
        print(f"  {name:<16} {short_hash(config.hashes[name], 12)}  {config.sources[name]}")
    return ExitCode.OK


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code and never lets an exception escape.

    The outer boundary is the fail-closed contract for *unexpected* failures (spec §17):
    an export or report bug used to print a raw traceback and exit 1, which leaks whatever
    the traceback contains, tells the operator nothing actionable, and breaks the exit-code
    contract CI depends on. Now it logs a redacted traceback and exits 3.
    """
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception:
        return int(_report_unexpected())


def _report_unexpected() -> ExitCode:
    """Log the traceback where it can be read, say something short, exit 3."""
    log_dir = Path("logs")
    logger = setup_logging("unexpected", log_dir=log_dir)
    logger.exception("unexpected error")
    print(
        "apex: unexpected error. Nothing was deployed. The full traceback is in "
        f"{log_dir}/unexpected.log (patient-identifying text is masked).",
        file=sys.stderr,
    )
    return ExitCode.ERROR


def _main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command not in {"version", "validate", "build"}:
        print(f"apex {args.command}: {NOT_IMPLEMENTED}", file=sys.stderr)
        return int(ExitCode.BAD_INVOCATION)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"apex: {exc}", file=sys.stderr)
        return int(ExitCode.BAD_INVOCATION)

    if args.command == "version":
        return int(_run_version_with(args, config))
    if args.command == "build":
        return int(_run_build(args, config))
    return int(_run_validate(args, config))


if __name__ == "__main__":
    raise SystemExit(main())
