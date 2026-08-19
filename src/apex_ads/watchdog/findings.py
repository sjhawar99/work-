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

## Why there is no `HELD_DEMAND` here

Spec §13.3 defines it as "a converting or high-intent term with no positive keyword
covering it". **Stage 1 cannot establish that, and has stopped claiming to.**

Two attempts both failed, in opposite directions. The first asked the *negative* match
engine whether a positive keyword matched. The second — after that was caught — asked
whether the workbook named the query literally, which is a different question wearing the
name. The third, and the reason it is gone rather than fixed again: `covered` is false for
both `NOT_IN_WORKBOOK` and `UNKNOWN`, so every `HELD_DEMAND` this module emitted was
actually **drift** (an unapproved live keyword served it) or **ignorance** (the export
named no keyword at all).

There is a deeper reason, and it is the one that settles it. A search-terms export contains
only demand that **actually served**. Demand Google never served is, by construction, not
in the file. So "this converted despite nothing covering it" is not a statement this
dataset can support at all, and no amount of care in the implementation would change that.

What the data does support kept its own name:

* `EXPLICIT_KEYWORD_GAP` — it converted, an approved keyword served it, and the workbook
  has no keyword for this query itself. An opportunity to bid and write for it deliberately.
* `UNAPPROVED_KEYWORD` — it served on a keyword the workbook does not contain, or on an
  approved keyword running where the workbook does not put it. Drift.
* `COVERAGE_UNKNOWN` — the export named no triggering keyword. Unknown, and said so.
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
    JUNK = "JUNK"
    CONCENTRATION = "CONCENTRATION"
    CLASSIFIER_UNRESOLVED = "CLASSIFIER_UNRESOLVED"
    UNAPPROVED_KEYWORD = "UNAPPROVED_KEYWORD"
    EXPLICIT_KEYWORD_GAP = "EXPLICIT_KEYWORD_GAP"
    COVERAGE_UNKNOWN = "COVERAGE_UNKNOWN"


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


def _lists(classification: Classification) -> str:
    """Name the negative **list**, never the negative's text.

    A negative's text can be exactly the query — `job` is on `ACCOUNT_JUNK`, and somebody
    searches `job`. Printing it into a finding put the query into the actions report and
    the dashboard, both of which are handle-only, without `SearchTerm` being involved at
    all. A list name cannot be a search term in any realistic account.
    """
    names = sorted({pattern.list_name for pattern in classification.patterns})
    return ", ".join(names) or "a negative list"


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
                    f" (claimed by {len(classification.matched)} specialties)"
                    if classification.matched
                    else ""
                ),
            )
        )

    if classification.category is Category.COMPETITOR:
        # Only a leak when an approved exclusion actually covers this campaign and the term
        # served anyway. Where the list deliberately does not reach the campaign, the policy
        # did exactly what Apex decided, and `INTENTIONAL_NON_REACH` says so in the
        # negative-policy section. Firing here as well made one event simultaneously
        # "approved behaviour" and "leakage" — the reader has no way to reconcile that, and
        # the one that looks like a defect is the one they act on.
        if any(pattern.reaches(row.campaign) for pattern in classification.patterns):
            found.append(
                make(
                    FindingType.BRAND_LEAK,
                    REVIEW,
                    "competitor-brand vocabulary served in a campaign an approved exclusion "
                    f"covers (the negative it matched is on {_lists(classification)}; named "
                    "in search_term_analysis.csv)",
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
        # Junk vocabulary is a statement about traffic quality, so it is reported whether or
        # not a list covers this campaign — unlike a "leak", which asserts a defect. But the
        # wording has to distinguish them, or an unreached list reads as an enforcement
        # failure here while the negative-policy section calls it approved policy.
        reached = any(pattern.reaches(row.campaign) for pattern in classification.patterns)
        found.append(
            make(
                FindingType.JUNK,
                FLAGGED,
                f"matches junk vocabulary on {_lists(classification)} "
                + (
                    "which covers this campaign"
                    if reached
                    else "which, by approved policy, does not cover this campaign"
                )
                + " (the negative is named in search_term_analysis.csv)",
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

    if row.conversions > 0 and routing.coverage.status is CoverageStatus.UNKNOWN:
        # The export named no triggering keyword, so nothing can be said about coverage.
        # Reported under its own name rather than folded into a finding that claims more.
        found.append(
            make(
                FindingType.COVERAGE_UNKNOWN,
                REVIEW,
                f"{row.conversions} conversion(s), and the export named no triggering "
                "keyword — whether an approved keyword covered this cannot be established",
            )
        )

    if routing.coverage.covered and not routing.coverage.has_own_keyword and row.conversions > 0:
        # An opportunity, not a gap in coverage: the demand is served, but by a broader
        # keyword, so it cannot be bid on or written for deliberately.
        found.append(
            make(
                FindingType.EXPLICIT_KEYWORD_GAP,
                _verdict(row.conversions, thresholds.explicit_keyword_gap_min_conversions),
                f"{row.conversions} conversion(s) on a covered query with no keyword of "
                "its own — consider adding one so it can be bid and written for",
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

    if routing.coverage.status is CoverageStatus.APPROVED_ELSEWHERE:
        # The keyword is approved; the ad group running it is not the one that owns it.
        # Checking only the text called this green.
        found.append(
            make(
                FindingType.UNAPPROVED_KEYWORD,
                REVIEW,
                "served by an approved keyword running in an ad group that does not own "
                "it in the workbook (named in search_term_analysis.csv)",
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
