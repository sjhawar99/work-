"""`MANUAL_STEPS.md` — everything Editor cannot safely encode (spec §11.4-§11.5).

This file is what stops the system pretending automation is magic. Anything that has to
be done by a person, in the Google Ads UI, appears here as an ordered, checkable step —
including every workbook field the export deliberately does not carry.
"""

from __future__ import annotations

from pathlib import Path

from apex_ads.compile_.transform import CompiledAccount
from apex_ads.models.config import Config
from apex_ads.models.workbook import WorkbookBundle

FILENAME = "MANUAL_STEPS.md"

PROCEDURE = """## Import procedure

1. Open Google Ads Editor and **get latest changes** for the account.
2. **Account → Import → From file.** Import the CSVs in this order:
   `campaigns` → `adgroups` → `keywords` → the negative files → any asset files.
3. Review the proposed changes in the import preview. **Do not post yet.**
4. Run **Check changes**. Resolve every error and warning it reports.
5. **Post.** Then confirm in Google Ads that every campaign shows status **Paused**.
6. Complete the manual steps listed above, in the Google Ads UI.
7. QA against `PRE_FLIGHT_REPORT.txt`, then record sign-off in `01 ACTIONS`.
8. Only then enable the campaigns — in the UI, deliberately, by a person.
"""

SCHEMA_WARNING = """> ⚠️ **The Editor column names in this build are unverified.**
>
> They were written from knowledge of Google Ads Editor, not copied from a real export of
> this account. Editor matches on exact English column names. Before the first real
> import, export the account from Editor and reconcile every header in
> `config/editor_schema.yaml` against that file. Until that is done, treat a clean
> "Check changes" as the real test, not this build.
"""


def _campaign_steps(bundle: WorkbookBundle) -> list[str]:
    lines: list[str] = []
    for campaign in sorted(bundle.campaigns, key=lambda c: c.name):
        lines.append(f"- **{campaign.name}**")
        lines.append(f"  - Location option: `{campaign.location_option}`")
        lines.append(f"  - Primary conversion: `{campaign.primary_conversion}`")
        if campaign.secondary_conversions:
            lines.append(f"  - Secondary conversions: `{campaign.secondary_conversions}`")
        lines.append(f"  - Call number: `{campaign.call_phone_number}`")
        lines.append(f"  - Call schedule: `{campaign.call_schedule}`")
        lines.append(f"  - Automation guardrails: `{campaign.automation_guardrails}`")
    return lines


def render(bundle: WorkbookBundle, account: CompiledAccount, config: Config, *, run_id: str) -> str:
    """Build the manual-steps document for one run."""
    schema = config.editor_schema
    lines = [
        "# MANUAL STEPS",
        "",
        f"Run `{run_id}` · workbook `{bundle.source_path.name}`",
        "",
        "The import files in this folder do **not** create everything. Google Ads Editor "
        "cannot encode the settings below, so a person sets them in the Google Ads UI "
        "after posting.",
        "",
        SCHEMA_WARNING,
        "",
        "## 1. Settings Editor cannot import",
        "",
    ]
    lines.extend(f"- {item.replace('_', ' ')}" for item in schema.manual_only)
    lines.extend(["", "## 2. Per-campaign settings to apply by hand", ""])
    lines.extend(_campaign_steps(bundle))

    lists = {row.list_name: row.applies_to for row in account.shared_list_rows}
    if lists:
        lines.extend(
            [
                "",
                "## 3. Shared negative lists",
                "",
                "`shared_negative_lists.csv` holds the terms. Creating a list and "
                "attaching it to campaigns may not import reliably, so verify each "
                "association by hand — a list attached to nothing protects nothing.",
                "",
            ]
        )
        for name, campaigns in sorted(lists.items()):
            members = sum(1 for row in account.shared_list_rows if row.list_name == name)
            lines.append(f"- **{name}** — {members} term(s), attach to:")
            lines.extend(f"  - {campaign}" for campaign in campaigns)

    lines.extend(["", "## 4. Workbook fields this build did not export", ""])
    lines.append(
        "Recorded so nothing goes missing unnoticed. These are configuration set by hand "
        "above, or workbook notes that were never account settings."
    )
    lines.append("")
    for name, entity in schema.entities.items():
        if entity.manual_only:
            lines.append(f"- `{name}` set by hand: {', '.join(sorted(entity.manual_only))}")
        if entity.documentation_only:
            lines.append(
                f"- `{name}` documentation only: {', '.join(sorted(entity.documentation_only))}"
            )

    lines.extend(["", PROCEDURE])
    return "\n".join(lines).rstrip() + "\n"


def write(
    directory: Path,
    bundle: WorkbookBundle,
    account: CompiledAccount,
    config: Config,
    *,
    run_id: str,
) -> Path:
    path = directory / FILENAME
    path.write_text(render(bundle, account, config, run_id=run_id), encoding="utf-8")
    return path
