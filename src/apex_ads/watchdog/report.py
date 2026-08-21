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
from apex_ads.util.searchterm import SearchTerm
from apex_ads.watchdog import present
from apex_ads.watchdog.findings import Analysed, FindingType, TermFinding, rank
from apex_ads.watchdog.ingest import Export
from apex_ads.watchdog.labels import safe_label
from apex_ads.watchdog.observations import (
    INTENTIONAL_NON_REACH,
    OBSERVED_DESPITE_NEGATIVE,
    Observation,
)
from apex_ads.watchdog.routing import CoverageStatus

FILENAME = "actions_report.txt"
WIDTH = 92

NO_THRESHOLDS = """WHY THRESHOLD-BASED FINDINGS SAY "REVIEW"

  Stage 1 sets no thresholds. There is not enough clean Apex data yet, and a cutoff
  invented today would quietly become policy forever. So this report ranks by money at
  stake and prints the observed figure; it does not declare any figure unacceptable.
  A person decides. When you later set a real number in config/rules.yaml, the same rows
  gain a verdict and nothing else changes.

  Rows can still say FLAGGED. A term matching a negative keyword you already approved is
  a deterministic hit on a decision a person took — there is no statistic to be careful
  about, so it is stated outright rather than softened into a suggestion.
"""

PRIVACY_NOTE = """  Search terms themselves are NOT in this file. Each is identified by a query ID.
  The words are in search_term_analysis.csv, which stays in output/ and is not committed.
"""

VISIBILITY_HEADING = "WHAT THIS FILE DOES NOT CONTAIN"


def _visibility(export: Export) -> str:
    """Rendered from the run's own visibility state, never from a standing paragraph.

    The standing paragraph told every reader "those searches happened and cost money" —
    on runs whose state was `NOT_PROVABLY_COMPLETE`, where nothing had established that
    anything was withheld at all. The machine-readable half of this run and the sentence a
    person read were making different claims.
    """
    return f"{VISIBILITY_HEADING}\n\n  {export.visibility.paragraph}\n"


def _rule(char: str = "-") -> str:
    return char * WIDTH


_money = present.money


def render(
    export: Export,
    analysed: list[Analysed],
    all_findings: list[TermFinding],
    observations: list[Observation],
    findings: list[Finding],
    config: Config,
    terms: list[SearchTerm],
    *,
    run_id: str,
    key_fingerprint: str,
) -> str:
    lines: list[str] = [
        "APEX GOOGLE ADS OS — SEARCH-TERM WATCHDOG",
        f"Run:        {run_id}",
        f"Export:     {export.path.name}",
    ]
    lines.append(f"Covering:   {present.window(export).line}")
    lines.extend(
        [
            f"Rows read:  {len(export.rows)}  ({len(export.parse_errors)} unreadable)",
            f"Spend:      {present.spend(export).line}",
            f"Query IDs:  keyed, fingerprint {key_fingerprint}",
            "",
            _rule("="),
            "",
            NO_THRESHOLDS,
            _visibility(export),
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
    lines.extend(_observations(observations, terms))
    lines.extend(
        [
            "",
            _rule("="),
            "",
            "WHAT TO DO WITH THIS",
            "",
            "  1. Open search_term_analysis.csv and read the top rows by cost.",
            "  2. Decide what is waste. If you want to block something, write the negative",
            "     yourself in 03 KEYWORDS — this tool does not write one for you.",
            "  3. negative_observations.csv holds TWO kinds of row. They need opposite",
            "     handling, so read the observation column first:",
            "",
            "       INTENTIONAL_NON_REACH     Information only. The list deliberately does",
            "                                 not cover that campaign and behaved as",
            "                                 approved. Do NOT investigate it, and do NOT",
            "                                 change which campaigns the list applies to —",
            "                                 that is a decision already taken.",
            "",
            "       OBSERVED_DESPITE_NEGATIVE Worth checking. An approved negative covers",
            "                                 that campaign and the term served anyway.",
            "                                 Check the export's date range first, then",
            "                                 whether the list is actually applied in the",
            "                                 account, then decide.",
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
    unapproved = sum(
        1 for item in analysed if item.routing.coverage.status is CoverageStatus.NOT_IN_WORKBOOK
    )
    unknown = sum(1 for item in analysed if item.routing.coverage.status is CoverageStatus.UNKNOWN)
    no_own = sum(1 for item in analysed if not item.routing.coverage.has_own_keyword)
    # Stated flatly, because the explanatory clause was an inference. "Served by a broader
    # keyword" is only established for rows the workbook covers; this count also includes
    # `NOT_IN_WORKBOOK` (served by a keyword we never approved) and `UNKNOWN` (the export
    # named no triggering keyword at all), for which nothing about the serving keyword is
    # known. The noun was factual and the parenthesis smuggled in a claim — the same shape as
    # every other defect this project has found.
    #
    # Two different numbers, and they used to share one label. `no_own` counts every query
    # with no exact keyword; the finding fires only where the query was *covered*, converted,
    # and still had no keyword of its own. A zero-conversion query raised the count without
    # producing a single opportunity, so the summary and the section below it disagreed.
    opportunities = sum(
        1 for finding in all_findings if finding.type is FindingType.EXPLICIT_KEYWORD_GAP
    )
    return [
        "SUMMARY",
        "",
        f"  Terms analysed          {len(analysed)}",
        f"  Classified              {resolved}",
        f"  Unresolved              {len(analysed) - resolved}   "
        "(read these; they improve the taxonomy)",
        f"  Routed elsewhere        {leaked}",
        f"  Workbook has no exact keyword  {no_own}",
        f"  Explicit-keyword opportunities {opportunities}   "
        "(of those, the converting ones — the EXPLICIT_KEYWORD_GAP finding)",
        f"  Served by an unapproved keyword {unapproved}",
        f"  Coverage unknown        {unknown}   (the export named no triggering keyword)",
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


def _observations(observations: list[Observation], terms: list[SearchTerm]) -> list[str]:
    """What was seen about negative policy. Nothing here is a proposal."""
    by_design = [item for item in observations if item.kind == INTENTIONAL_NON_REACH]
    despite = [item for item in observations if item.kind == OBSERVED_DESPITE_NEGATIVE]
    lines = [
        _rule(),
        f"NEGATIVE POLICY  —  {len(by_design)} excluded by design, {len(despite)} seen "
        "despite an approved negative",
        _rule(),
        "",
        "  The Watchdog does not write negative keywords for you, and does not propose",
        "  changing which campaigns a list covers. Both are strategy decisions. What",
        "  follows is what was observed; deciding is yours.",
        "",
    ]
    if by_design:
        lines.extend(
            [
                "  EXCLUDED BY DESIGN — the list deliberately does not cover this campaign.",
                "  Nothing to do; shown so the cost is visible.",
                "",
            ]
        )
        for item in by_design:
            label = safe_label(item.negative_text, terms)
            lines.append(f"  {label:<28} {item.list_name:<20} served in {item.incident_campaign}")
            lines.append(
                f"          {_money(item.cost)} across {len(item.query_ids)} term(s); "
                f"approved reach: {', '.join(item.approved_reach) or 'all campaigns'}"
            )
    if despite:
        lines.extend(
            ["", "  SEEN DESPITE AN APPROVED NEGATIVE — check date range, then the account:", ""]
        )
        for item in despite:
            label = safe_label(item.negative_text, terms)
            lines.append(f"  {label:<28} {item.list_name:<20} served in {item.incident_campaign}")
            lines.append(f"          {_money(item.cost)} across {len(item.query_ids)} term(s)")
    if not observations:
        lines.append("  (none)")
    lines.append("")
    return lines


def write(
    directory: Path,
    export: Export,
    analysed: list[Analysed],
    all_findings: list[TermFinding],
    observations: list[Observation],
    findings: list[Finding],
    config: Config,
    terms: list[SearchTerm],
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
            observations,
            findings,
            config,
            terms,
            run_id=run_id,
            key_fingerprint=key_fingerprint,
        ),
        encoding="utf-8",
    )
    return path
