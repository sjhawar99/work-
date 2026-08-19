"""Running every validator and collecting every finding.

The runner does not stop at the first BLOCKER. A human fixing a workbook wants the whole
list in one pass, in workbook order, not one problem per run.

A validator that raises is itself reported as a BLOCKER rather than crashing the run:
one broken rule must not hide the findings of the other seventeen.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.policy import WAIVABLE_RULE_IDS
from apex_ads.validate.base import Validator
from apex_ads.validate.registry import validators_for

SEVERITY_ORDER = {Severity.BLOCKER: 0, Severity.WARNING: 1, Severity.INFO: 2}
RUNNER_FAILURE_RULE = "VAL-999"

Mode = Literal["validate", "build"]
"""`validate` is a health check; `build` is producing something importable."""


@dataclass(frozen=True)
class ValidationResult:
    """Everything one validation pass produced."""

    findings: tuple[Finding, ...]

    @property
    def blockers(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.BLOCKER)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    @property
    def infos(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.INFO)

    @property
    def passed(self) -> bool:
        return not self.blockers

    def counts(self) -> dict[str, int]:
        return {
            "BLOCKER": len(self.blockers),
            "WARNING": len(self.warnings),
            "INFO": len(self.infos),
        }


def _sort_key(finding: Finding) -> tuple[int, str, int, str]:
    return (
        SEVERITY_ORDER[finding.severity],
        finding.sheet,
        finding.row if finding.row is not None else 0,
        finding.rule_id,
    )


def merge(result: ValidationResult, extra: Iterable[Finding]) -> ValidationResult:
    """One final finding set: validation plus everything the compile stage discovered.

    `EXP-001` (a workbook field with nowhere to go) and `EXP-002` (a record type routed to
    a destination that cannot carry it) are found after validation has finished, inside
    the build. Keeping them in a separate list meant the pre-flight report — the document
    a human actually reads — could say `BUILD FAILED` and then list nothing wrong.

    Sorted the same way, so a merged report reads exactly like an unmerged one.
    """
    combined = [*result.findings, *extra]
    return ValidationResult(findings=tuple(sorted(combined, key=_sort_key)))


def is_waivable(rule_id: str) -> bool:
    """Stage 1: nothing is waivable. Kept as plumbing so the answer stays explicit."""
    return rule_id in WAIVABLE_RULE_IDS


def run(
    bundle: WorkbookBundle,
    rules: Rules,
    *,
    validators: tuple[Validator, ...] | None = None,
    mode: Mode = "validate",
) -> ValidationResult:
    """Run every validator over the bundle and return all findings, worst first."""
    findings: list[Finding] = list(bundle.findings)

    for validator in validators if validators is not None else validators_for():
        ready_only = getattr(validator, "ready_only", False)
        try:
            produced = list(validator.check(bundle, rules))
            if ready_only and mode == "validate":
                produced = [
                    finding.model_copy(
                        update={
                            "severity": Severity.WARNING,
                            "message": finding.message + " (blocks a deployable build)",
                        }
                    )
                    if finding.severity is Severity.BLOCKER
                    else finding
                    for finding in produced
                ]
            findings.extend(produced)
        except Exception as exc:  # a broken rule must not hide the other rules' findings
            findings.append(
                Finding(
                    rule_id=RUNNER_FAILURE_RULE,
                    severity=Severity.BLOCKER,
                    message=f"validator {validator.rule_id} failed to run: {exc!r}",
                    sheet="—",
                    remedy="This is a bug in the tool, not in the workbook.",
                )
            )

    return ValidationResult(findings=tuple(sorted(findings, key=_sort_key)))
