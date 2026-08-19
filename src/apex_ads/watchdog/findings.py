"""Watchdog finding types — rank and surface, do not adjudicate (spec §13.3).

**Stage 1 has no thresholds.** Every cutoff in `watchdog.thresholds` is `null` on purpose:
there is no clean Apex data yet, and a number invented today would silently become policy
forever. So the Watchdog may say *"this query took 34% of last week's Ortho spend"*. It may
not say 34% is unacceptable, because nobody has decided that.

`null` therefore means **rank-and-review**: sort by money at stake, print the observed
figure, attach no verdict. When a human later sets a real number — after
`learn_thresholds_after_days` of clean data — the same finding gains a verdict and the
code path is identical. Only the config changes.

The rule this module exists to enforce, stated once so it cannot drift:

> A validator must never invent a default when a threshold is `null`. `null` means "we do
> not know yet", and the honest implementation of "we do not know yet" is to show the
> evidence and let a person decide.

`_verdict()` is the only place a threshold is read, and it returns `REVIEW` whenever the
threshold is `None`. There is no other path.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from apex_ads.models.config import WatchdogRules
from apex_ads.watchdog.ingest import SearchTermRow
from apex_ads.watchdog.routing import CoverageStatus, Routing
from apex_ads.watchdog.taxonomy import Category, Classification

REVIEW = "REVIEW"
"""No threshold is set, so this is evidence for a human, not a verdict."""

FLAGGED = "FLAGGED"
"""A threshold was set by a person and this row is past it."""

WITHIN = "WITHIN"


class FindingType(str, Enum):
    BRAND_LEAK = "BRAND_LEAK"
    SPECIALTY_LEAK = "SPECIALTY_LEAK"
    HELD_DEMAND = "HELD_DEMAND"
    JUNK = "JUNK"
    CONCENTRATION = "CONCENTRATION"
    CLASSIFIER_UNRESOLVED = "CLASSIFIER_UNRESOLVED"
    UNAPPROVED_KEYWORD = "UNAPPROVED_KEYWORD"


@dataclass(frozen=True)
class TermFinding:
    """One finding about one query. Carries the handle, never the query."""

    type: FindingType
    query_id: str
    verdict: str
    """`REVIEW`, `FLAGGED` or `WITHIN`. `REVIEW` is Stage 1's normal answer."""
    detail: str
    cost: Decimal
    clicks: int
    impressions: int
    conversions: Decimal
    expected: str
    actual: str

    @property
    def money_at_stake(self) -> Decimal:
        return self.cost

    def as_record(self) -> dict[str, str]:
        return {
            "finding": self.type.value,
            "query_id": self.query_id,
            "verdict": self.verdict,
            "detail": self.detail,
            "expected_owner": self.expected,
            "actual_owner": self.actual,
            "impressions": str(self.impressions),
            "clicks": str(self.clicks),
            "cost": f"{self.cost:.2f}",
            "conversions": f"{self.conversions:.2f}",
        }


@dataclass(frozen=True)
class Analysed:
    """One export row after classification and routing — the analysis CSV's unit."""

    row: SearchTermRow
    classification: Classification
    routing: Routing
    findings: tuple[TermFinding, ...]


def _verdict(observed: Decimal | int, threshold: Decimal | int | None) -> str:
    """The only place a Stage-1 threshold is consulted.

    `None` returns `REVIEW`. There is deliberately no `or default` anywhere in this module:
    that single character is how "we have no data yet" turns into invented policy.
    """
    if threshold is None:
        return REVIEW
    return FLAGGED if Decimal(str(observed)) >= Decimal(str(threshold)) else WITHIN


def _owner(text: str) -> str:
    return text or "—"


def for_row(
    row: SearchTermRow,
    classification: Classification,
    routing: Routing,
    rules: WatchdogRules,
) -> list[TermFinding]:
    """Every finding this row earns. Deterministic; no thresholds except through `_verdict`."""
    found: list[TermFinding] = []
    thresholds = rules.thresholds
    actual = str(routing.actual)
    expected = str(routing.expected) if routing.expected else "—"

    def make(kind: FindingType, verdict: str, detail: str) -> TermFinding:
        return TermFinding(
            type=kind,
            query_id=row.query_id,
            verdict=verdict,
            detail=detail,
            cost=row.cost,
            clicks=row.clicks,
            impressions=row.impressions,
            conversions=row.conversions,
            expected=_owner(expected),
            actual=_owner(actual),
        )

    if classification.category is Category.UNRESOLVED:
        found.append(
            make(
                FindingType.CLASSIFIER_UNRESOLVED,
                REVIEW,
                "no taxonomy rule resolved this term"
                + (
                    f" (ambiguous: {', '.join(classification.matched)})"
                    if classification.matched
                    else ""
                ),
            )
        )

    if classification.category is Category.COMPETITOR:
        found.append(
            make(
                FindingType.BRAND_LEAK,
                REVIEW,
                "competitor-brand vocabulary served at all "
                f"(matched {', '.join(classification.matched)})",
            )
        )
    elif classification.category is Category.BRAND and routing.leaked:
        found.append(
            make(
                FindingType.BRAND_LEAK,
                REVIEW,
                f"brand term served by {actual}, not by the brand campaign",
            )
        )
    elif classification.category is Category.SPECIALTY and routing.leaked:
        found.append(
            make(
                FindingType.SPECIALTY_LEAK,
                REVIEW,
                f"{routing.expected_specialty} term served by {actual}",
            )
        )

    if classification.category is Category.JUNK_VOCABULARY:
        # Vocabulary matches are reported outright: a human already put these words on a
        # junk list, so no statistical judgement is involved.
        found.append(
            make(
                FindingType.JUNK,
                FLAGGED,
                "matches junk vocabulary already on a negative list "
                f"({', '.join(classification.matched)})",
            )
        )
    elif row.impressions and not row.clicks:
        # Statistical junk. Ranked, never auto-declared.
        found.append(
            make(
                FindingType.JUNK,
                _verdict(row.impressions, thresholds.junk_min_impressions),
                f"{row.impressions} impression(s), no clicks",
            )
        )

    if row.conversions > 0 and not routing.coverage.has_own_keyword:
        # "Converted, and the workbook has no keyword of its own for it."
        #
        # Deliberately an identity test against the workbook, not a matching test. The
        # first version asked "does any positive keyword match this query?" and answered it
        # with the *negative* match engine, which under-reports positive coverage — so a
        # query Google was already serving perfectly well was reported as held demand.
        #
        # What this says now is narrow and true: it converted, and you have no keyword
        # naming it, so you cannot bid on it or write copy for it deliberately.
        found.append(
            make(
                FindingType.HELD_DEMAND,
                _verdict(row.conversions, thresholds.held_demand_min_conversions),
                f"{row.conversions} conversion(s); the workbook has no keyword of its own "
                f"for this query ({routing.coverage.describe()})",
            )
        )

    if routing.coverage.status is CoverageStatus.NOT_IN_WORKBOOK:
        # Not demand — drift. The account served this on a keyword the approved workbook
        # does not contain. Reported so it is visible; adjudicating it is Phase 7's job.
        found.append(
            make(
                FindingType.UNAPPROVED_KEYWORD,
                REVIEW,
                "served by a keyword that is not in the approved workbook "
                "(named in search_term_analysis.csv)",
            )
        )

    return found


def concentration(
    analysed: list[Analysed],
    rules: WatchdogRules,
    incomplete: frozenset[str] | None = None,
) -> list[TermFinding]:
    """Spend share per query within its campaign. `rank_and_review` decides nothing.

    Share is computed **within the campaign**, not across the account: a query taking 34%
    of Ortho is a fact about Ortho, and dividing by the whole account would make every
    small campaign look innocent.

    **A share requires a complete denominator.** `incomplete` names campaigns whose totals
    cannot be trusted because a row that belongs to them failed to parse. Row-level
    evidence survives a parse error; an aggregate does not — one unreadable expensive row
    turns a genuine 25% into a printed 70%, and nothing about the output would look wrong.
    For those campaigns the absolute cost is still reported and the percentage is refused,
    which is the same discipline `UNKNOWN` gets everywhere else in this project.
    """
    blocked = incomplete or frozenset()
    totals: dict[str, Decimal] = {}
    for item in analysed:
        totals[item.row.campaign] = totals.get(item.row.campaign, Decimal("0")) + item.row.cost

    findings: list[TermFinding] = []
    for item in analysed:
        total = totals.get(item.row.campaign, Decimal("0"))
        if total <= 0 or item.row.cost <= 0:
            continue
        verdict = REVIEW
        if item.row.campaign in blocked:
            detail = (
                f"{item.row.cost:.2f} in {item.row.campaign}; share NOT COMPUTED — a row "
                "in this campaign could not be read, so the campaign total is incomplete"
            )
        else:
            share = (item.row.cost / total).quantize(Decimal("0.0001"))
            computed = _verdict(share, rules.thresholds.concentration_spend_share)
            if rules.concentration_mode != "rank_and_review":
                verdict = computed
            detail = (
                f"{share * 100:.1f}% of {item.row.campaign} spend "
                f"({item.row.cost:.2f} of {total:.2f})"
            )
        findings.append(
            TermFinding(
                type=FindingType.CONCENTRATION,
                query_id=item.row.query_id,
                verdict=verdict,
                detail=detail,
                cost=item.row.cost,
                clicks=item.row.clicks,
                impressions=item.row.impressions,
                conversions=item.row.conversions,
                expected=_owner(str(item.routing.expected) if item.routing.expected else "—"),
                actual=_owner(str(item.routing.actual)),
            )
        )
    findings.sort(key=lambda finding: finding.cost, reverse=True)
    return findings


def rank(findings: list[TermFinding]) -> list[TermFinding]:
    """Money at stake, descending. The only ordering the report uses."""
    return sorted(
        findings,
        key=lambda finding: (-finding.cost, -finding.clicks, finding.type.value, finding.query_id),
    )
