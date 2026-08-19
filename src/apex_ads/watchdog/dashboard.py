"""`dashboard.html` — the same numbers, easier to scan (spec §13.6).

Self-contained: no external stylesheet, no script, no font, no image. A dashboard that
fetches anything is a dashboard that leaks which account opened it and stops working
offline, and the operator opens this from a local folder.

Like the actions report, it carries **no raw queries** — this is the file most likely to
be screenshotted or forwarded. Handles only; the words live in the git-ignored CSV.

Nothing here computes a verdict. Where a row says `REVIEW` the dashboard says `REVIEW`,
and the header explains why rather than leaving a reader to assume the tool failed.
"""

from __future__ import annotations

import html
from decimal import Decimal
from pathlib import Path

from apex_ads.util.searchterm import SearchTerm
from apex_ads.watchdog.findings import FindingType, TermFinding, rank
from apex_ads.watchdog.ingest import Export
from apex_ads.watchdog.labels import safe_label
from apex_ads.watchdog.observations import (
    INTENTIONAL_NON_REACH,
    OBSERVED_DESPITE_NEGATIVE,
    Observation,
)

FILENAME = "dashboard.html"

STYLE = """
:root { color-scheme: light dark; --ink:#1a1a1a; --bg:#fff; --line:#d8d8d8;
        --muted:#666; --warn:#8a5a00; --stop:#8a1c1c; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e8e8e8; --bg:#161616; --line:#3a3a3a; --muted:#9a9a9a;
          --warn:#e0b050; --stop:#e08080; } }
* { box-sizing: border-box; }
body { margin:0; padding:2rem 1.25rem; background:var(--bg); color:var(--ink);
       font:15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 74rem; margin: 0 auto; }
h1 { font-size:1.35rem; margin:0 0 .25rem; }
h2 { font-size:1.05rem; margin:2rem 0 .5rem; }
.meta { color:var(--muted); font-size:.86rem; margin-bottom:1.5rem; }
.note { border:1px solid var(--line); border-left:3px solid var(--warn);
        padding:.85rem 1rem; margin:1rem 0 1.75rem; font-size:.9rem; }
.cards { display:flex; flex-wrap:wrap; gap:.75rem; margin:1rem 0; }
.card { border:1px solid var(--line); padding:.7rem .95rem; min-width:9.5rem; }
.card .n { font-size:1.5rem; font-variant-numeric:tabular-nums; }
.card .l { color:var(--muted); font-size:.78rem; text-transform:uppercase;
           letter-spacing:.04em; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:.88rem; }
th, td { text-align:left; padding:.4rem .6rem; border-bottom:1px solid var(--line);
         vertical-align:top; }
th { font-weight:600; color:var(--muted); font-size:.78rem; text-transform:uppercase;
     letter-spacing:.04em; }
td.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
code { font:.85em ui-monospace, SFMono-Regular, Menlo, monospace; }
.v { font-size:.75rem; padding:.05rem .4rem; border:1px solid var(--line); }
.stop { color:var(--stop); }
footer { margin-top:2.5rem; color:var(--muted); font-size:.82rem;
         border-top:1px solid var(--line); padding-top:1rem; }
"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def render(
    export: Export,
    term_findings: list[TermFinding],
    observations: list[Observation],
    terms: list[SearchTerm],
    *,
    run_id: str,
) -> str:
    first, last = export.observed_dates
    covering = f"{first} to {last}" if first and last else "range unverified (no day column)"
    by_design = [item for item in observations if item.kind == INTENTIONAL_NON_REACH]
    despite = [item for item in observations if item.kind == OBSERVED_DESPITE_NEGATIVE]

    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Search-Term Watchdog — {_e(run_id)}</title>",
        f"<style>{STYLE}</style></head><body><main>",
        "<h1>Search-Term Watchdog</h1>",
        f"<p class='meta'>Run <code>{_e(run_id)}</code> · export "
        f"<code>{_e(export.path.name)}</code> · covering {_e(covering)}</p>",
        "<div class='note'><strong>Every row says REVIEW on purpose.</strong> Stage 1 sets "
        "no thresholds — there is not enough clean data yet, and a cutoff invented today "
        "would quietly become policy. This page ranks by money at stake and decides "
        "nothing.<br><br>Search terms are not shown here. Each is identified by a query ID; "
        "the words are in <code>search_term_analysis.csv</code>, which is not committed.</div>",
        "<div class='cards'>",
        _card(len(export.rows), "terms read"),
        _card(_money(export.total_cost), "spend"),
        _card(len(term_findings), "findings"),
        _card(len(by_design), "excluded by design"),
        _card(len(despite), "seen despite a negative"),
        _card(len(export.parse_errors), "unreadable rows"),
        "</div>",
    ]

    for kind in FindingType:
        rows = rank([finding for finding in term_findings if finding.type is kind])
        if not rows:
            continue
        total = sum((row.cost for row in rows), Decimal("0"))
        parts.append(f"<h2>{_e(kind.value)} — {len(rows)} row(s), {_money(total)} at stake</h2>")
        parts.append("<div class='scroll'><table><thead><tr>")
        parts.append(
            "<th>verdict</th><th>query</th><th>detail</th><th>expected</th>"
            "<th>actual</th><th class='n'>cost</th><th class='n'>clicks</th>"
            "<th class='n'>conv</th></tr></thead><tbody>"
        )
        for row in rows[:40]:
            parts.append(
                "<tr>"
                f"<td><span class='v'>{_e(row.verdict)}</span></td>"
                f"<td><code>{_e(row.query_id)}</code></td>"
                f"<td>{_e(row.detail)}</td>"
                f"<td>{_e(row.expected)}</td>"
                f"<td>{_e(row.actual)}</td>"
                f"<td class='n'>{_money(row.cost)}</td>"
                f"<td class='n'>{row.clicks}</td>"
                f"<td class='n'>{row.conversions:.2f}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
        if len(rows) > 40:
            parts.append(f"<p class='meta'>{len(rows) - 40} more in search_term_analysis.csv</p>")

    parts.append(f"<h2>Negative policy — {len(observations)} observation(s)</h2>")
    parts.append(
        "<p class='meta'>Observations only. The Watchdog does not write negative keywords "
        "and does not propose changing which campaigns a list covers — both are strategy "
        "decisions for a person.</p>"
    )
    parts.append("<div class='scroll'><table><thead><tr>")
    parts.append(
        "<th>observation</th><th>negative</th><th>list</th><th>served in</th>"
        "<th class='n'>terms</th><th class='n'>cost</th><th>what to do</th>"
        "</tr></thead><tbody>"
    )
    for item in observations[:40]:
        parts.append(
            f"<tr><td>{_e(item.kind)}</td>"
            f"<td><code>{_e(safe_label(item.negative_text, terms))}</code></td>"
            f"<td>{_e(item.list_name)}</td><td>{_e(item.incident_campaign)}</td>"
            f"<td class='n'>{len(item.query_ids)}</td>"
            f"<td class='n'>{_money(item.cost)}</td><td>{_e(item.remedy)}</td></tr>"
        )
    if not observations:
        parts.append("<tr><td colspan='7'>none</td></tr>")
    parts.append("</tbody></table></div>")

    parts.append(
        "<footer>This tool changed nothing. It has no access to the Google Ads account, "
        "and it did not modify the workbook. Every change is made by a person, in the "
        "workbook, and enforced by the next <code>apex build</code>.</footer>"
    )
    parts.append("</main></body></html>")
    return "".join(parts)


def _card(value: object, label: str) -> str:
    return (
        f"<div class='card'><div class='n'>{_e(value)}</div><div class='l'>{_e(label)}</div></div>"
    )


def write(
    directory: Path,
    export: Export,
    term_findings: list[TermFinding],
    observations: list[Observation],
    terms: list[SearchTerm],
    *,
    run_id: str,
) -> Path:
    path = directory / FILENAME
    path.write_text(
        render(export, term_findings, observations, terms, run_id=run_id), encoding="utf-8"
    )
    return path
