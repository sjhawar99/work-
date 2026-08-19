"""`--propose-writeback` — new files only (spec §13.7).

**The source workbook is never modified.** This emits paste-ready blocks into
`<run_id>/writeback/`, and a human copies what they approve into the Google Sheet. The
next `apex build` then enforces it.

That indirection is the entire audit trail. If the Watchdog wrote into the workbook, the
sheet would stop being a record of what people decided and become a record of what two
programs decided between them, and the question "who approved this negative" would have no
answer. Going through a person is not friction here; it is the control.

The guardrail test asserts this module has no write path outside the run directory, and
`test_guardrails.py` asserts no source file anywhere writes into `input/`.
"""

from __future__ import annotations

import csv
from pathlib import Path

from apex_ads.watchdog.findings import FindingType, TermFinding, rank
from apex_ads.watchdog.suggestions import SUGGESTION, Candidate

DIRECTORY = "writeback"
KEYWORDS_BLOCK = "03_KEYWORDS_append.csv"
ACTIONS_BLOCK = "01_ACTIONS_append.csv"
README = "HOW_TO_PASTE.txt"

KEYWORD_HEADERS = [
    "Campaign",
    "Ad group",
    "Scope",
    "Type",
    "Match type",
    "Keyword text",
    "COPY / PASTE VALUE",
    "List name",
    "Status",
    "Why",
]

ACTION_HEADERS = [
    "Date raised",
    "Task or problem",
    "Type",
    "Required action / next step",
    "Owner",
    "Status",
    "Severity",
]

INSTRUCTIONS = """HOW TO USE THESE FILES

These are NOT changes. Nothing here has been applied to anything.

  03_KEYWORDS_append.csv   rows you can paste at the bottom of the 03 KEYWORDS table
  01_ACTIONS_append.csv    rows you can paste into the RUNNING ACTIONS table

What to do:

  1. Open each file and read it. Delete any row you disagree with. That is the point of
     the file being separate: disagreeing costs one keypress.
  2. Paste the rows you kept into the matching table in the Google Sheet.
  3. Set Status yourself. Every row arrives as PROPOSED and the compiler treats an
     unapproved row as unapproved.
  4. Export the sheet to input/workbook.xlsx and run apex build.

Nothing reaches Google Ads until you do step 4, and even then only through Google Ads
Editor, by a person.

The workbook itself was NOT modified by this run. It never is.
"""


def _write(path: Path, headers: list[str], rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _copy_paste(text: str, match_type: str) -> str:
    """The workbook's derived column, regenerated the same way the compiler does (KW-009)."""
    if match_type == "PHRASE":
        return f'"{text}"'
    if match_type == "EXACT":
        return f"[{text}]"
    return text


def _scope(candidate: Candidate) -> str:
    if candidate.level == "ACCOUNT":
        return "Account"
    if candidate.level == "CAMPAIGN":
        return f"Campaign: {candidate.scope}"
    return "Ad group"


def keyword_rows(candidates: list[Candidate]) -> list[dict[str, str]]:
    """One row per suggestion, in the workbook's own column order.

    `ROUTING_CONFLICT` candidates are deliberately **excluded**: they are the ones the
    collision engine refused, and a paste-ready row is an invitation to paste.
    """
    rows: list[dict[str, str]] = []
    for candidate in candidates:
        if candidate.status != SUGGESTION:
            continue
        campaign, _, ad_group = candidate.scope.partition(" / ")
        rows.append(
            {
                "Campaign": campaign if candidate.level != "ACCOUNT" else "—",
                "Ad group": ad_group or "—",
                "Scope": _scope(candidate),
                "Type": "Negative",
                "Match type": candidate.match_type.capitalize(),
                "Keyword text": candidate.text,
                "COPY / PASTE VALUE": _copy_paste(candidate.text, candidate.match_type),
                "List name": "" if candidate.level != "ACCOUNT" else "ACCOUNT_JUNK",
                "Status": "PROPOSED",
                "Why": (
                    f"Watchdog: {candidate.reason}; would have removed "
                    f"{len(candidate.blocked_query_ids)} term(s), {candidate.cost:.2f} spend"
                ),
            }
        )
    return rows


def action_rows(term_findings: list[TermFinding], *, run_id: str) -> list[dict[str, str]]:
    """One action per finding type that needs a human decision, not one per term.

    Nine hundred rows nobody reads is the same as no rows. The action names the type, the
    money at stake and where to look.
    """
    rows: list[dict[str, str]] = []
    for kind in (FindingType.HELD_DEMAND, FindingType.CLASSIFIER_UNRESOLVED):
        found = rank([finding for finding in term_findings if finding.type is kind])
        if not found:
            continue
        total = sum((finding.cost for finding in found), start=found[0].cost * 0)
        rows.append(
            {
                "Date raised": "",
                "Task or problem": f"{kind.value}: {len(found)} term(s) from run {run_id}",
                "Type": "Watchdog",
                "Required action / next step": (
                    f"Review the {kind.value} section of actions_report.txt "
                    f"({total:.2f} at stake) and decide. No thresholds are set, so this is "
                    "evidence, not a verdict."
                ),
                "Owner": "Gaurav",
                "Status": "Open",
                "Severity": "AMBER",
            }
        )
    return rows


def write(
    directory: Path, candidates: list[Candidate], term_findings: list[TermFinding], *, run_id: str
) -> list[Path]:
    """Emit the writeback bundle inside the run directory. Never anywhere else."""
    target = directory / DIRECTORY
    target.mkdir(parents=True, exist_ok=True)
    written = [
        _write(target / KEYWORDS_BLOCK, KEYWORD_HEADERS, keyword_rows(candidates)),
        _write(target / ACTIONS_BLOCK, ACTION_HEADERS, action_rows(term_findings, run_id=run_id)),
    ]
    readme = target / README
    readme.write_text(INSTRUCTIONS, encoding="utf-8")
    written.append(readme)
    return written
