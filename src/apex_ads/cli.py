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
from apex_ads.models.config import ConfigError, load_config
from apex_ads.util.hashing import short_hash

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


def _run_version(args: argparse.Namespace) -> ExitCode:
    config = load_config(args.config)
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

    if args.command != "version":
        print(f"apex {args.command}: {NOT_IMPLEMENTED}", file=sys.stderr)
        return int(ExitCode.BAD_INVOCATION)

    try:
        return int(_run_version(args))
    except ConfigError as exc:
        print(f"apex: {exc}", file=sys.stderr)
        return int(ExitCode.BAD_INVOCATION)


if __name__ == "__main__":
    raise SystemExit(main())
