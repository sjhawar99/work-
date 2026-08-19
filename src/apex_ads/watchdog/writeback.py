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

## There is no keyword block any more

`03_KEYWORDS_append.csv` is gone, and its absence is the deliverable.

Stage 1's Watchdog does not author negative policy (see `observations.py`), so it has
nothing to put in a keyword row. The version that did emit one produced two kinds of
invalid output: for an already-approved negative it said "add `job` to `ACCOUNT_JUNK`"
when `job` was already there, and for a reach change it wrote a `Shared list → …` scope
naming full campaign names where the workbook uses short aliases — a row that would not
round-trip through this project's own `ScopeParser`, and that `NEG-008` would block anyway
because only one of the three routing sources was updated.

An action a person acts on is the honest output. A paste-ready row that the next compiler
run rejects is worse than no row.
"""

from __future__ import annotations

import csv
from pathlib import Path

from apex_ads.watchdog.findings import FindingType, TermFinding, rank
from apex_ads.watchdog.observations import (
    OBSERVED_DESPITE_NEGATIVE,
    POLICY_SCOPE_REVIEW,
    Observation,
)

DIRECTORY = "writeback"
ACTIONS_BLOCK = "01_ACTIONS_append.csv"
README = "HOW_TO_PASTE.txt"

ACTION_HEADERS = [
    "Date raised",
    "Task or problem",
    "Type",
    "Required action / next step",
    "Owner",
    "Status",
    "Severity",
]

INSTRUCTIONS = """HOW TO USE THIS FILE

This is NOT a change. Nothing here has been applied to anything.

  01_ACTIONS_append.csv    rows you can paste into the RUNNING ACTIONS table

There is deliberately no keyword file. The Watchdog does not write negative keywords for
you, and it does not propose changes to which campaigns a shared list covers. Both of
those are decisions about strategy, and this tool reports evidence rather than making
them.

What to do:

  1. Open the file and read it. Delete any row you disagree with.
  2. Paste the rows you kept into RUNNING ACTIONS in the Google Sheet.
  3. Work the actions. If one of them leads you to change a keyword or a list, you make
     that change yourself, in the sheet, deliberately.
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


def action_rows(
    term_findings: list[TermFinding], observations: list[Observation], *, run_id: str
) -> list[dict[str, str]]:
    """One action per finding type that needs a human decision, not one per term.

    Nine hundred rows nobody reads is the same as no rows. The action names the type, the
    money at stake and where to look.
    """
    rows: list[dict[str, str]] = []
    for kind in (
        FindingType.HELD_DEMAND,
        FindingType.EXPLICIT_KEYWORD_GAP,
        FindingType.CLASSIFIER_UNRESOLVED,
        FindingType.UNAPPROVED_KEYWORD,
    ):
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

    for observation_kind, label in (
        (POLICY_SCOPE_REVIEW, "negative list does not cover where a term served"),
        (OBSERVED_DESPITE_NEGATIVE, "a term served despite an approved negative"),
    ):
        matching = [item for item in observations if item.kind == observation_kind]
        if not matching:
            continue
        total = sum((item.cost for item in matching), start=matching[0].cost * 0)
        rows.append(
            {
                "Date raised": "",
                "Task or problem": (
                    f"{observation_kind}: {len(matching)} case(s) from run {run_id}"
                ),
                "Type": "Watchdog",
                "Required action / next step": (
                    f"{label} ({total:.2f} at stake). See negative_observations.csv. The "
                    "Watchdog proposes no change to keywords or list reach — decide and "
                    "make any change yourself."
                ),
                "Owner": "Gaurav",
                "Status": "Open",
                "Severity": "AMBER",
            }
        )
    return rows


def write(
    directory: Path,
    observations: list[Observation],
    term_findings: list[TermFinding],
    *,
    run_id: str,
) -> list[Path]:
    """Emit the writeback bundle inside the run directory. Never anywhere else."""
    target = directory / DIRECTORY
    target.mkdir(parents=True, exist_ok=True)
    written = [
        _write(
            target / ACTIONS_BLOCK,
            ACTION_HEADERS,
            action_rows(term_findings, observations, run_id=run_id),
        )
    ]
    readme = target / README
    readme.write_text(INSTRUCTIONS, encoding="utf-8")
    written.append(readme)
    return written
