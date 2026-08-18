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
from pathlib import Path
from typing import NoReturn

from apex_ads import __version__
from apex_ads.exit_codes import ExitCode
from apex_ads.ingest.errors import WorkbookError
from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import Config, ConfigError, load_config
from apex_ads.models.findings import Finding
from apex_ads.report import preflight
from apex_ads.util.hashing import short_hash
from apex_ads.util.logging import setup_logging
from apex_ads.util.runid import make as make_run_id
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
    result = run_validators(bundle, config.rules)

    report = preflight.write(
        args.out / run_id, bundle, result, run_id=run_id, config_hashes=config.hashes
    )
    print(report.read_text(encoding="utf-8"))
    print(f"report written to {report}", file=sys.stderr)
    return ExitCode.OK if result.passed else ExitCode.BLOCKER


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
    """Entry point. Returns a process exit code; never raises for expected failures."""
    args = build_parser().parse_args(argv)

    if args.command not in {"version", "validate"}:
        print(f"apex {args.command}: {NOT_IMPLEMENTED}", file=sys.stderr)
        return int(ExitCode.BAD_INVOCATION)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"apex: {exc}", file=sys.stderr)
        return int(ExitCode.BAD_INVOCATION)

    if args.command == "version":
        return int(_run_version_with(args, config))
    return int(_run_validate(args, config))


if __name__ == "__main__":
    raise SystemExit(main())
