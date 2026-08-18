"""The pre-flight report (spec §12).

Plain text, ≤100 columns, readable in a terminal or pasted into a chat. Every line a
human might act on carries workbook coordinates and a remedy.

Nothing in here may state that a check passed when it did not run. Phase 2 has no URL
checking, so the header says so rather than staying silent about it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.util.hashing import short_hash
from apex_ads.validate.runner import ValidationResult

WIDTH = 100
SYMBOLS = {Severity.BLOCKER: "❌", Severity.WARNING: "⚠️", Severity.INFO: "•"}


def _wrap(text: str, indent: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = " " * indent
    for word in words:
        if len(current) + len(word) + 1 > WIDTH:
            lines.append(current.rstrip())
            current = " " * indent
        current += word + " "
    if current.strip():
        lines.append(current.rstrip())
    return lines


def _where(finding: Finding) -> str:
    location = finding.sheet
    if finding.row is not None:
        location += f" r{finding.row}"
    return location


def _block(title: str, findings: tuple[Finding, ...]) -> list[str]:
    if not findings:
        return []
    lines = [title]
    for raw in findings:
        finding = raw.redacted()
        lines.append(f"  [{finding.rule_id}] {_where(finding):<16} {finding.message}")
        if finding.remedy:
            lines.extend(_wrap(f"Fix: {finding.remedy}", indent=12))
    lines.append("")
    return lines


def render(
    bundle: WorkbookBundle,
    result: ValidationResult,
    *,
    run_id: str,
    config_hashes: dict[str, str],
    url_checks: str = "NOT RUN — landing-page checking arrives in Phase 4",
    outcome: str | None = None,
) -> str:
    """Render the full report. `outcome` overrides the computed PASS/FAIL headline."""
    counts = result.counts()
    verdict = outcome or ("VALIDATION PASSED" if result.passed else "VALIDATION FAILED")

    lines = [
        "APEX GOOGLE ADS OS — PRE-FLIGHT REPORT",
        f"Run:        {run_id}",
        f"Workbook:   {bundle.source_path}  (sha256 {short_hash(bundle.source_sha256, 12)}…)",
        f"Exported:   {bundle.source_mtime:%Y-%m-%d %H:%M}  "
        "— local file age only; not proof it matches the Google Sheet",
        f"Rules:      config/rules.yaml    "
        f"(sha256 {short_hash(config_hashes.get('rules', ''), 12)}…)",
        f"URL checks: {url_checks}",
        "",
        f"RESULT: {verdict} — {counts['BLOCKER']} BLOCKERS, {counts['WARNING']} WARNINGS",
        "",
        "SUMMARY",
    ]

    lines.extend(_summary(bundle, result))
    lines.append("")
    lines.extend(_block("BLOCKERS", result.blockers))
    lines.extend(_block("WARNINGS", result.warnings))
    lines.extend(_block("INFO", result.infos))

    if not result.passed:
        lines.append("NO DEPLOYABLE FILES GENERATED")
    return "\n".join(lines).rstrip() + "\n"


def _summary(bundle: WorkbookBundle, result: ValidationResult) -> list[str]:
    failing = {finding.rule_id for finding in result.blockers}
    monthly = sum(campaign.monthly_budget for campaign in bundle.campaigns)
    open_red = sum(1 for finding in result.blockers if finding.rule_id == "ACT-001")
    broad = sum(1 for keyword in bundle.keywords if keyword.match_type == "BROAD")
    collisions = sum(1 for finding in result.blockers if finding.rule_id == "NEG-001")

    rows = [
        ("Monthly budget", f"₹{monthly:,.0f}", "BUD-001" in failing),
        ("Campaigns", str(len(bundle.campaigns)), "STR-001" in failing),
        ("Ad groups", str(len(bundle.ad_groups)), "STR-002" in failing),
        ("Positive keywords", str(len(bundle.keywords)), False),
        ("Negatives", str(len(bundle.negatives)), False),
        ("Broad positives", str(broad), broad > 0),
        ("Negative collisions", str(collisions), collisions > 0),
        ("Landing pages", str(len(bundle.landing_pages)), "STR-LP-001" in failing),
        ("Open RED blockers", str(open_red), open_red > 0),
    ]
    return [f"  {'❌' if failed else '✅'} {label:<22} {value}" for label, value, failed in rows]


def write(
    directory: Path,
    bundle: WorkbookBundle,
    result: ValidationResult,
    *,
    run_id: str,
    config_hashes: dict[str, str],
    url_checks: str = "NOT RUN — landing-page checking arrives in Phase 4",
) -> Path:
    """Write `PRE_FLIGHT_REPORT.txt` and `findings.json`. Returns the report path."""
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "PRE_FLIGHT_REPORT.txt"
    report.write_text(
        render(bundle, result, run_id=run_id, config_hashes=config_hashes, url_checks=url_checks),
        encoding="utf-8",
    )

    payload = {
        "run_id": run_id,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workbook": {
            "path": str(bundle.source_path),
            "sha256": bundle.source_sha256,
            "mtime": bundle.source_mtime.isoformat(timespec="seconds"),
        },
        "config_sha256": config_hashes,
        "url_checks": url_checks,
        "counts": result.counts(),
        "passed": result.passed,
        "findings": [finding.redacted().model_dump() for finding in result.findings],
    }
    (directory / "findings.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report
