"""`actions_report.txt` — the human summary (spec §13.6).

Ranked by money at stake, and carrying **no raw queries**. This is the file somebody
forwards, pastes into a message, or reads out on a Monday call, so it names handles and
points at `search_term_analysis.csv` for the words.

The report also states, in plain words, that Stage 1 sets no thresholds. Without that
sentence a reader sees `REVIEW` beside every row and assumes the tool failed to decide;
with it, they understand it declined to, and why.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from apex_ads.models.config import Config
from apex_ads.models.findings import Finding, Severity
from apex_ads.watchdog.findings import Analysed, FindingType, TermFinding, rank
from apex_ads.watchdog.ingest import Export
from apex_ads.watchdog.suggestions import ROUTING_CONFLICT, SUGGESTION, Candidate

FILENAME = "actions_report.txt"
WIDTH = 92

NO_THRESHOLDS = """WHY EVERY ROW SAYS "REVIEW"

  Stage 1 sets no thresholds. There is not enough clean Apex data yet, and a cutoff
  invented today would quietly become policy forever. So this report ranks by money at
  stake and prints the observed figure; it does not declare any figure unacceptable.
  A person decides. When you later set a real number in config/rules.yaml, the same rows
  gain a verdict and nothing else changes.
"""

PRIVACY_NOTE = """  Search terms themselves are NOT in this file. Each is identified by a query ID.
  The words are in search_term_analysis.csv, which stays in output/ and is not committed.
"""


def _rule(char: str = "-") -> str:
    return char * WIDTH


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def render(
    export: Export,
    analysed: list[Analysed],
    all_findings: list[TermFinding],
    candidates: list[Candidate],
    findings: list[Finding],
    config: Config,
    *,
    run_id: str,
    key_fingerprint: str,
) -> str:
    lines: list[str] = [
        "APEX GOOGLE ADS OS — SEARCH-TERM WATCHDOG",
        f"Run:        {run_id}",
        f"Export:     {export.path.name}",
    ]
    first, last = export.observed_dates
    if first and last:
        lines.append(f"Covering:   {first} to {last}")
    else:
        lines.append(
            "Covering:   UNKNOWN — the export has no day column, so the range is unverified"
        )
    lines.extend(
        [
            f"Rows read:  {len(export.rows)}  ({len(export.parse_errors)} unreadable)",
            f"Spend:      {_money(export.total_cost)}",
            f"Query IDs:  keyed, fingerprint {key_fingerprint}",
            "",
            _rule("="),
            "",
            NO_THRESHOLDS,
            PRIVACY_NOTE,
            _rule("="),
            "",
        ]
    )

    blockers = [finding for finding in findings if finding.severity is Severity.BLOCKER]
    warnings = [finding for finding in findings if finding.severity is Severity.WARNING]

    if blockers:
        lines.extend(["BLOCKERS", ""])
        lines.extend(_findings(blockers))
        lines.append("")
    if warnings:
        lines.extend(["WARNINGS", ""])
        lines.extend(_findings(warnings))
        lines.append("")

    lines.extend(_summary(analysed, all_findings))
    lines.extend(_by_type(all_findings))
    lines.extend(_candidates(candidates))
    lines.extend(
        [
            "",
            _rule("="),
            "",
            "WHAT TO DO WITH THIS",
            "",
            "  1. Open search_term_analysis.csv and read the top rows by cost.",
            "  2. For each one you agree is waste, copy the suggested negative from",
            "     negatives_suggestions.csv into 03 KEYWORDS of the workbook.",
            "  3. Anything marked ROUTING_CONFLICT is NOT suggested — it would block a",
            "     keyword you pay for. Decide it by hand, or leave it.",
            "  4. Record what you changed in 01 ACTIONS.",
            "  5. Re-run apex build. Nothing here reaches Google until you do.",
            "",
            "  This tool changed nothing. It has no access to your Google Ads account.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _findings(findings: list[Finding]) -> list[str]:
    lines = []
    for finding in findings:
        lines.append(f"  [{finding.rule_id}] {finding.message}")
        if finding.remedy:
            lines.append(f"            Fix: {finding.remedy}")
    return lines


def _summary(analysed: list[Analysed], all_findings: list[TermFinding]) -> list[str]:
    resolved = sum(1 for item in analysed if item.classification.resolved)
    leaked = sum(1 for item in analysed if item.routing.leaked)
    uncovered = sum(1 for item in analysed if not item.routing.coverage.covered)
    return [
        "SUMMARY",
        "",
        f"  Terms analysed          {len(analysed)}",
        f"  Classified              {resolved}",
        f"  Unresolved              {len(analysed) - resolved}   "
        "(read these; they improve the taxonomy)",
        f"  Routed elsewhere        {leaked}",
        f"  Not covered by keywords {uncovered}",
        f"  Findings raised         {len(all_findings)}",
        "",
    ]


def _by_type(all_findings: list[TermFinding]) -> list[str]:
    lines: list[str] = []
    for kind in FindingType:
        rows = rank([finding for finding in all_findings if finding.type is kind])
        if not rows:
            continue
        total = sum((row.cost for row in rows), Decimal("0"))
        lines.extend(
            [
                _rule(),
                f"{kind.value}  —  {len(rows)} row(s), {_money(total)} at stake",
                _rule(),
                "",
            ]
        )
        for row in rows[:20]:
            lines.append(
                f"  {row.verdict:<8} {row.query_id:<16} {_money(row.cost):>10}  {row.detail}"
            )
            if row.expected != "—" and row.expected != row.actual:
                lines.append(f"           {'':<16} {'':>10}  expected {row.expected}")
        if len(rows) > 20:
            lines.append(f"  … {len(rows) - 20} more in search_term_analysis.csv")
        lines.append("")
    return lines


def _candidates(candidates: list[Candidate]) -> list[str]:
    suggestions = [item for item in candidates if item.status == SUGGESTION]
    conflicts = [item for item in candidates if item.status == ROUTING_CONFLICT]
    lines = [
        _rule(),
        f"SUGGESTED NEGATIVES  —  {len(suggestions)} candidate(s), "
        f"{len(conflicts)} withheld as ROUTING_CONFLICT",
        _rule(),
        "",
        "  Candidates only. Nothing is applied. Paste what you agree with into 03 KEYWORDS.",
        "",
    ]
    for item in suggestions[:25]:
        lines.append(f"  {item.match_type:<7} {item.text:<28} {item.level:<9} {item.scope}")
        lines.append(
            f"          would have removed {len(item.blocked_query_ids)} term(s), "
            f"{_money(item.cost)} spend, {item.conversions:.2f} conversion(s)"
        )
    if not suggestions:
        lines.append("  (none)")
    if conflicts:
        lines.extend(["", "  WITHHELD — these would block keywords you pay for:", ""])
        for item in conflicts:
            lines.append(f"  {item.match_type:<7} {item.text:<28} {item.level:<9} {item.scope}")
            for blocked in item.conflicts_with[:4]:
                lines.append(f"          would block: {blocked}")
    lines.append("")
    return lines


def write(
    directory: Path,
    export: Export,
    analysed: list[Analysed],
    all_findings: list[TermFinding],
    candidates: list[Candidate],
    findings: list[Finding],
    config: Config,
    *,
    run_id: str,
    key_fingerprint: str,
) -> Path:
    path = directory / FILENAME
    path.write_text(
        render(
            export,
            analysed,
            all_findings,
            candidates,
            findings,
            config,
            run_id=run_id,
            key_fingerprint=key_fingerprint,
        ),
        encoding="utf-8",
    )
    return path
