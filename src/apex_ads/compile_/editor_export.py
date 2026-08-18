"""Writing Google Ads Editor import files (spec §11).

Schema-driven: the writer iterates `config/editor_schema.yaml` and knows nothing about
any particular column. Adding a column is a config change.

Two guarantees are enforced in code rather than trusted:

* **No field disappears silently.** A model field that is neither mapped, nor declared
  manual-only, nor declared documentation-only raises `UnmappedFieldError`. That is how
  a future `Audience exclusion` column fails loudly instead of being quietly dropped.
* **Everything is Paused.** The writer re-asserts it after the transform already did,
  because this is the last place it could go wrong (guardrail §18.15).
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from apex_ads.compile_.transform import CompiledAccount, SharedListRow
from apex_ads.models.config import ColumnMap, EditorSchema, EntityMap, NegativeArtifact
from apex_ads.models.findings import Finding, Severity

PAUSED = "Paused"
PROVENANCE = {"sheet", "row", "section"}
UNMAPPED_RULE = "EXP-001"
INVENTORY_RULE = "EXP-002"

QUOTING: dict[str, Literal[0, 1, 2, 3]] = {
    "minimal": csv.QUOTE_MINIMAL,
    "all": csv.QUOTE_ALL,
    "none": csv.QUOTE_NONE,
}


class UnmappedFieldError(Exception):
    """A model field reached the writer with nowhere to go."""


class NotPausedError(Exception):
    """A row reached the writer without `Paused` status. Should be unreachable."""


@dataclass(frozen=True)
class WrittenFile:
    """One emitted file and how much is in it."""

    path: Path
    rows: int


def _transform_value(value: Any, transform: str | None) -> str:
    if value is None:
        return ""
    if transform == "currency":
        return f"{Decimal(str(value)):.2f}" if value != "" else ""
    if transform == "match_type":
        return str(value).capitalize()
    if transform == "paused":
        if str(value) != PAUSED:
            raise NotPausedError(f"refusing to write status {value!r}; expected {PAUSED!r}")
        return PAUSED
    if transform == "join_semicolon":
        if isinstance(value, list | tuple):
            return "; ".join(str(item) for item in value)
        return str(value)
    return str(value)


def _row_values(record: Any, columns: list[ColumnMap]) -> dict[str, str]:
    values: dict[str, str] = {}
    for column in columns:
        raw = getattr(record, column.model_field, None)
        rendered = _transform_value(raw, column.transform)
        if column.required and not rendered:
            raise UnmappedFieldError(
                f"required column {column.editor_column!r} is empty for {record!r}"
            )
        values[column.editor_column] = rendered
    return values


def check_unmapped(records: Iterable[Any], entity: EntityMap, name: str) -> list[Finding]:
    """Every non-empty model field must be mapped, manual, or documentation.

    This is the Phase-5 parking-lot requirement: no non-empty workbook field may vanish
    from a deployable build without somebody deciding where it goes.
    """
    mapped = {column.model_field for column in entity.columns}
    known = mapped | set(entity.manual_only) | set(entity.documentation_only) | PROVENANCE

    findings: list[Finding] = []
    reported: set[str] = set()
    for record in records:
        for field_name in type(record).model_fields:
            if field_name in known or field_name in reported:
                continue
            value = getattr(record, field_name, None)
            if value in (None, "", [], {}):
                continue
            reported.add(field_name)
            findings.append(
                Finding(
                    rule_id=UNMAPPED_RULE,
                    severity=Severity.BLOCKER,
                    message=f"UNMAPPED SOURCE FIELD: {name}.{field_name} carries a value "
                    "but is neither exported, nor a manual step, nor marked as "
                    "documentation",
                    sheet=getattr(record, "sheet", "—"),
                    section=name,
                    entity=field_name,
                    remedy="Add it to columns, manual_only or documentation_only in "
                    "config/editor_schema.yaml. Deciding is the point — a field that "
                    "nobody classified is a field that silently goes missing.",
                )
            )
    return findings


def check_inventory(account: CompiledAccount, schema: EditorSchema) -> list[Finding]:
    """Every record type the compiler produced must have a declared destination.

    `EXP-001` is field-level: it catches a column nobody mapped inside a record type the
    exporter already knows about. It cannot see a record type that never reaches the
    exporter at all — which is how nine responsive search ads and twelve supporting
    assets once vanished from a build that reported itself READY.

    This is the entity-level guard. Undeclared record type with rows in it → BLOCKER.
    """
    findings: list[Finding] = []
    for name, records in account.collections().items():
        if not records:
            continue
        if name not in schema.inventory:
            findings.append(
                Finding(
                    rule_id=INVENTORY_RULE,
                    severity=Severity.BLOCKER,
                    message=f"EXPORT INVENTORY: {len(records)} {name} row(s) were compiled "
                    "but the record type has no declared destination",
                    sheet="config/editor_schema.yaml",
                    section="inventory",
                    entity=name,
                    remedy=f"Add `{name}: editor` or `{name}: manual_steps` to inventory in "
                    "config/editor_schema.yaml. A record type nobody classified is a "
                    "record type that silently goes missing.",
                )
            )
    return findings


def _write(
    path: Path, headers: list[str], rows: list[dict[str, str]], schema: EditorSchema
) -> WrittenFile:
    dialect = schema.csv
    with path.open("w", encoding=dialect.encoding, newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=headers,
            lineterminator=dialect.line_terminator,
            quoting=QUOTING[dialect.quoting],
        )
        writer.writeheader()
        writer.writerows(rows)
    return WrittenFile(path=path, rows=len(rows))


def write_entity(
    directory: Path, records: list[Any], entity: EntityMap, schema: EditorSchema
) -> WrittenFile:
    headers = [column.editor_column for column in entity.columns]
    rows = [_row_values(record, entity.columns) for record in records]
    return _write(directory / entity.file, headers, rows, schema)


def write_negative_artifact(
    directory: Path,
    records: list[Any],
    artifact: NegativeArtifact,
    schema: EditorSchema,
) -> WrittenFile:
    headers = [column.editor_column for column in artifact.columns]
    rows = [_row_values(record, artifact.columns) for record in records]
    return _write(directory / artifact.file, headers, rows, schema)


def write_all(
    directory: Path, account: CompiledAccount, schema: EditorSchema
) -> tuple[list[WrittenFile], list[Finding]]:
    """Write every import file. Returns what was written and any unmapped-field findings."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[WrittenFile] = []
    findings: list[Finding] = check_inventory(account, schema)

    entities: list[tuple[str, list[Any]]] = [
        ("campaigns", list(account.campaigns)),
        ("ad_groups", list(account.ad_groups)),
        ("keywords", list(account.keywords)),
    ]
    for name, records in entities:
        entity = schema.entities[name]
        findings.extend(check_unmapped(records, entity, name))
        written.append(write_entity(directory, records, entity, schema))

    buckets: dict[str, list[Any]] = {
        "account_negatives": list(account.account_negatives),
        "shared_negative_lists": list(account.shared_list_rows),
        "campaign_negatives": list(account.campaign_negatives),
        "adgroup_negatives": list(account.adgroup_negatives),
    }
    for name, records in buckets.items():
        artifact = schema.negative_artifacts[name]
        written.append(write_negative_artifact(directory, records, artifact, schema))

    return written, findings


def shared_list_campaigns(rows: list[SharedListRow]) -> dict[str, tuple[str, ...]]:
    """List name → the campaigns it serves, for MANUAL_STEPS.md."""
    return {row.list_name: row.applies_to for row in rows}
