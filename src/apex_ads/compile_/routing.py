"""Route integrity: a label is not a conveyor belt (`EXP-002`).

`EXP-001` is field-level. `EXP-002` was entity-level but only checked *membership* — that
a record type appeared somewhere in `inventory`. That is not the same as checking the
declared destination can actually carry it.

The hole it left was precise and easy to fall into. Changing one line:

    ads: manual_steps   ->   ads: editor

produced a READY build with seven files, no ads in any of them, no finding, and
`MANUAL_STEPS.md` silently stopping listing them — because `write_all()` has no RSA
writer and the manual renderer only runs when the destination says `manual_steps`. The
inventory proudly declared everything accounted for while nine ads disappeared.

So the guard now asks three questions, not one:

    A  compiled collection has no destination                      -> BLOCKER
    B  destination is `editor` but no Editor writer exists         -> BLOCKER
    C  destination is `manual_steps` but no manual renderer exists  -> BLOCKER

Capability is declared by the modules that actually do the work, so a destination cannot
claim a handler that is not there.
"""

from __future__ import annotations

from apex_ads.compile_.transform import CompiledAccount
from apex_ads.models.config import EditorSchema
from apex_ads.models.findings import Finding, Severity

INVENTORY_RULE = "EXP-002"


def _finding(message: str, entity: str, remedy: str) -> Finding:
    return Finding(
        rule_id=INVENTORY_RULE,
        severity=Severity.BLOCKER,
        message=f"EXPORT INVENTORY: {message}",
        sheet="config/editor_schema.yaml",
        section="inventory",
        entity=entity,
        remedy=remedy,
    )


def check_routes(account: CompiledAccount, schema: EditorSchema) -> list[Finding]:
    """Every non-empty record type must have a destination that can actually carry it."""
    from apex_ads.compile_.editor_export import EDITOR_WRITERS
    from apex_ads.compile_.manual_steps import MANUAL_RENDERERS

    findings: list[Finding] = []
    for name, records in account.collections().items():
        if not records:
            continue

        destination = schema.inventory.get(name)

        if destination is None:
            findings.append(
                _finding(
                    f"{len(records)} {name} row(s) were compiled but the record type has "
                    "no declared destination",
                    name,
                    f"Add `{name}: editor` or `{name}: manual_steps` to inventory in "
                    "config/editor_schema.yaml. A record type nobody classified is a "
                    "record type that silently goes missing.",
                )
            )
            continue

        if destination == "editor" and name not in EDITOR_WRITERS:
            findings.append(
                _finding(
                    f"{name} is routed to `editor`, but no Editor writer exists for it, so "
                    f"its {len(records)} row(s) would be written nowhere",
                    name,
                    f"Implement an Editor writer and column mapping for {name}, or route "
                    "it to `manual_steps` until one exists. A destination with no handler "
                    "is a label on an empty conveyor belt.",
                )
            )

        if destination == "manual_steps" and name not in MANUAL_RENDERERS:
            findings.append(
                _finding(
                    f"{name} is routed to `manual_steps`, but MANUAL_STEPS.md has no "
                    f"renderer for it, so its {len(records)} row(s) would be described "
                    "nowhere",
                    name,
                    f"Add a renderer for {name} in compile_/manual_steps.py, or route it "
                    "to `editor` once a writer exists.",
                )
            )

    return findings
