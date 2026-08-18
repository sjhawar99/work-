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

from apex_ads.ingest.urlcheck import UrlResult
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
        prefix = f"  [{finding.rule_id}] {_where(finding):<16} "
        first = prefix + finding.message
        if len(first) <= WIDTH:
            lines.append(first)
        else:
            # Long messages wrap under a hanging indent rather than running off the page.
            lines.append(prefix.rstrip())
            lines.extend(_wrap(finding.message, indent=12))
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
    url_checks: str = "NOT RUN",
    url_results: dict[str, UrlResult] | None = None,
    outcome: str | None = None,
) -> str:
    """Render the full report. `outcome` overrides the computed PASS/FAIL headline."""
    counts = result.counts()
    verdict = outcome or ("VALIDATION PASSED" if result.passed else "VALIDATION FAILED")
    footer_needed = not result.passed or (outcome or "").endswith("DRAFT")

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
    lines.extend(_landing_pages(url_results))
    lines.extend(_block("BLOCKERS", result.blockers))
    lines.extend(_block("WARNINGS", result.warnings))
    lines.extend(_block("INFO", result.infos))

    if footer_needed:
        lines.append(
            "NO DEPLOYABLE FILES GENERATED"
            if not result.passed
            else "NOT DEPLOYABLE - quarantined, see DO_NOT_IMPORT.txt"
        )
    return "\n".join(lines).rstrip() + "\n"


def _landing_pages(results: dict[str, UrlResult] | None) -> list[str]:
    """Per-destination results. UNKNOWN is printed as UNKNOWN, never folded into a pass."""
    if not results:
        return []
    lines = ["LANDING PAGES"]
    for path, check in results.items():
        latency = f"{check.latency_seconds:.2f}s" if check.latency_seconds is not None else ""
        detail = str(check.http_status) if check.http_status else check.reason
        if len(detail) > 40:
            # The full text is preserved in findings.json; the table stays readable.
            detail = detail[:37] + "…"
        lines.append(f"  {check.status:<9} {path:<38} {detail:<41} {latency}")
    lines.append("")
    return lines


def _summary(bundle: WorkbookBundle, result: ValidationResult) -> list[str]:
    failing = {finding.rule_id for finding in result.blockers}
    monthly = sum(campaign.monthly_budget for campaign in bundle.campaigns)
    open_red = sum(1 for finding in result.blockers if finding.rule_id == "ACT-001")
    broad = sum(1 for keyword in bundle.keywords if keyword.match_type == "BROAD")
    collision_findings = [f for f in result.blockers if f.rule_id == "NEG-001"]
    unknown = [f for f in collision_findings if "collision status UNKNOWN" in f.message]
    collisions = str(len(collision_findings) - len(unknown))
    if unknown:
        collisions = f"UNKNOWN ({len(unknown)} negative(s) not evaluated)"

    rows = [
        ("Monthly budget", f"₹{monthly:,.0f}", "BUD-001" in failing),
        ("Campaigns", str(len(bundle.campaigns)), "STR-001" in failing),
        ("Ad groups", str(len(bundle.ad_groups)), "STR-002" in failing),
        ("Positive keywords", str(len(bundle.keywords)), False),
        ("Negatives", str(len(bundle.negatives)), False),
        ("Broad positives", str(broad), broad > 0),
        ("Negative collisions", collisions, bool(unknown) or collisions != "0"),
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
    url_checks: str = "NOT RUN",
    url_results: dict[str, UrlResult] | None = None,
    outcome: str | None = None,
) -> Path:
    """Write `PRE_FLIGHT_REPORT.txt` and `findings.json`. Returns the report path."""
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "PRE_FLIGHT_REPORT.txt"
    report.write_text(
        render(
            bundle,
            result,
            run_id=run_id,
            config_hashes=config_hashes,
            url_checks=url_checks,
            url_results=url_results,
            outcome=outcome,
        ),
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
        "landing_pages": [
            {"path": path, **check.__dict__} for path, check in (url_results or {}).items()
        ],
        "counts": result.counts(),
        "passed": result.passed,
        "findings": [finding.redacted().model_dump() for finding in result.findings],
    }
    (directory / "findings.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report
