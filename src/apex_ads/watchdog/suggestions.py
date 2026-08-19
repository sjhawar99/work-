"""Candidate negatives, and the two gates they must pass (spec §13.5).

Suggestions are **never applied**. They are candidates a human pastes into `03 KEYWORDS`
if they agree, after which the next compiler run enforces them. That is the whole safety
model: the Watchdog proposes into the workbook, and the workbook is the only thing that
reaches the account.

## Where a candidate's text is allowed to come from

**Only from an approved negative that already exists in the workbook.** Nothing here
invents a negative, and nothing here derives one from a token.

Two earlier versions did, and both were dangerous:

* the taxonomy exploded `ck birla hospital` into `{ck, birla, hospital}`, so a single
  matched token could have become an account-wide broad negative on `hospital`;
* a `SPECIALTY_LEAK` proposed the matched specialty token as a broad negative, which is a
  transformation nobody approved — and the only *narrow* alternative, the query itself,
  is the patient's words and must not leave `search_term_analysis.csv`.

So a specialty leak now produces a routing issue and no negative at all. The remedy for a
term served by the wrong campaign is routing, and saying so is more useful than a negative
somebody has to reason about.

## Where a candidate's reach is allowed to come from

**From the list the negative already belongs to.** `ROUTE_COMPETITORS` is approved against
four campaigns with Brand deliberately excluded; a Google account-level negative applies
everywhere. Sending competitor negatives to `ACCOUNT` silently widened approved policy,
and the writeback then relabelled every account-level candidate `ACCOUNT_JUNK` — so a
competitor term arrived next Friday as junk vocabulary, and the Watchdog was rewriting the
meaning of its own evidence week to week.

A `Candidate` therefore carries `destination_list` and `executable_reach` from the pattern
it came from, and the writeback preserves both.

## What a candidate actually says

Since the text is always already approved, the finding is never "add this word". It is one
of two things about *reach* or *enforcement*:

| | meaning |
| --- | --- |
| `NOT_REACHED` | the negative exists, but its list does not reach the campaign that |
| | served the query. Extend the list. |
| `NOT_ENFORCED` | the list does reach that campaign, and the query served anyway — the |
| | approved negative is not live in the account. |

Both then pass the compiler's scope-aware collision engine; a candidate that would block a
positive we pay for becomes `ROUTING_CONFLICT` rather than a suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apex_ads.models.config import Rules
from apex_ads.models.workbook import Keyword
from apex_ads.validate.collisions import matches
from apex_ads.watchdog.findings import Analysed, FindingType
from apex_ads.watchdog.taxonomy import Category, NegativePattern, Taxonomy

SUGGESTION = "SUGGESTION"
ROUTING_CONFLICT = "ROUTING_CONFLICT"

NOT_REACHED = "NOT_REACHED"
NOT_ENFORCED = "NOT_ENFORCED"

ACCOUNT = "ACCOUNT"
SHARED_LIST = "SHARED_LIST"


@dataclass(frozen=True)
class Candidate:
    """A proposed negative-list change, or the conflict that stopped it becoming one."""

    status: str
    """`SUGGESTION` or `ROUTING_CONFLICT`. Never anything that reads as "applied"."""
    action: str
    """`NOT_REACHED` or `NOT_ENFORCED` — what is actually wrong."""
    text: str
    match_type: str
    destination_list: str
    """The approved list this negative already belongs to. Never inferred from a level."""
    level: str
    """`ACCOUNT` or `SHARED_LIST` — the list's own kind, not a scope chosen here."""
    executable_reach: tuple[str, ...]
    """The campaigns the destination list actually reaches today. `()` at `ACCOUNT` means
    every campaign, which is why an account list can never be `NOT_REACHED`."""
    incident_campaign: str
    """Where the query actually served — the campaign the reach fails to cover."""
    reason: str
    blocked_query_ids: tuple[str, ...]
    impressions: int
    clicks: int
    cost: Decimal
    conversions: Decimal
    conflicts_with: tuple[str, ...] = ()
    """Positive keywords this candidate would block. Non-empty exactly when the status is
    `ROUTING_CONFLICT`."""

    @property
    def scope(self) -> str:
        if self.level == ACCOUNT:
            return "Account"
        return f"Shared list → {', '.join(self.executable_reach) or '(reaches nothing)'}"

    def as_record(self) -> dict[str, str]:
        return {
            "status": self.status,
            "action": self.action,
            "negative_text": self.text,
            "match_type": self.match_type,
            "destination_list": self.destination_list,
            "level": self.level,
            "executable_reach": ", ".join(self.executable_reach)
            or ("all campaigns" if self.level == ACCOUNT else "none"),
            "incident_campaign": self.incident_campaign,
            "reason": self.reason,
            "would_have_blocked": str(len(self.blocked_query_ids)),
            "query_ids": " ".join(self.blocked_query_ids),
            "impressions": str(self.impressions),
            "clicks": str(self.clicks),
            "cost": f"{self.cost:.2f}",
            "conversions": f"{self.conversions:.2f}",
            "conflicts_with": " | ".join(self.conflicts_with),
        }


@dataclass(frozen=True)
class Evidence:
    """What one candidate would have removed last period."""

    query_ids: tuple[str, ...]
    impressions: int
    clicks: int
    cost: Decimal
    conversions: Decimal


def _conflicts(
    pattern: NegativePattern, incident_campaign: str, positives: list[Keyword]
) -> list[str]:
    """Positive keywords this candidate would block, **within the reach it would gain**.

    Scope-aware, exactly like `NEG-*`: for a `NOT_REACHED` candidate the new reach is the
    incident campaign, so only that campaign's positives are at risk. Reporting collisions
    account-wide would produce the wall of false blockers that teaches people to stop
    reading the report.
    """
    blocked: list[str] = []
    for keyword in positives:
        if not keyword.text:
            continue
        if pattern.level != ACCOUNT and keyword.campaign != incident_campaign:
            continue
        if matches(pattern.text, pattern.match_type, keyword.text):
            blocked.append(f"{keyword.text} ({keyword.match_type.lower()}) in {keyword.key}")
    return blocked


def build(
    analysed: list[Analysed], taxonomy: Taxonomy, positives: list[Keyword], rules: Rules
) -> list[Candidate]:
    """Propose reach or enforcement changes for approved negatives that failed to block."""
    # (pattern, incident campaign) -> the rows it explains
    grouped: dict[tuple[str, str, str, str], list[Analysed]] = {}
    patterns: dict[tuple[str, str, str, str], NegativePattern] = {}

    for item in analysed:
        kinds = {finding.type for finding in item.findings}
        category = item.classification.category

        # Spec §13.5 names JUNK, **competitor** BRAND_LEAK and SPECIALTY_LEAK. Own-brand
        # leak is excluded — it is a routing problem, and treating it as a suggestion
        # source once produced `negative: apex (broad)`, a proposal to stop bidding on
        # Apex's own name. SPECIALTY_LEAK is excluded too, because its only defensible
        # texts are an unapproved token or the patient's own words.
        eligible = (FindingType.JUNK in kinds and category is Category.JUNK_VOCABULARY) or (
            FindingType.BRAND_LEAK in kinds and category is Category.COMPETITOR
        )
        if not eligible:
            continue

        for pattern in item.classification.patterns:
            key = (pattern.text, pattern.match_type, pattern.list_name, item.row.campaign)
            grouped.setdefault(key, []).append(item)
            patterns[key] = pattern

    candidates: list[Candidate] = []
    for key, items in grouped.items():
        pattern = patterns[key]
        incident = key[3]
        evidence = _evidence(items)
        reached = pattern.reaches(incident)
        action = NOT_ENFORCED if reached else NOT_REACHED

        if action == NOT_REACHED:
            base = (
                f"{pattern.label()} is approved, but {pattern.list_name} does not reach "
                f"{incident!r}, which served the query"
            )
        else:
            base = (
                f"{pattern.label()} is approved and {pattern.list_name} does reach "
                f"{incident!r}, yet the query served — the negative is not live in the account"
            )

        conflicts = _conflicts(pattern, incident, positives)
        candidates.append(
            Candidate(
                status=ROUTING_CONFLICT if conflicts else SUGGESTION,
                action=action,
                text=pattern.text,
                match_type=pattern.match_type,
                destination_list=pattern.list_name,
                level=pattern.level,
                executable_reach=pattern.reach,
                incident_campaign=incident,
                reason=(
                    base
                    if not conflicts
                    else f"{base}; NOT SUGGESTED — extending it would block "
                    f"{len(conflicts)} positive keyword(s) we pay for"
                ),
                blocked_query_ids=evidence.query_ids,
                impressions=evidence.impressions,
                clicks=evidence.clicks,
                cost=evidence.cost,
                conversions=evidence.conversions,
                conflicts_with=tuple(conflicts),
            )
        )

    candidates.sort(
        key=lambda candidate: (-candidate.cost, candidate.text, candidate.incident_campaign)
    )
    return candidates


def _evidence(items: list[Analysed]) -> Evidence:
    return Evidence(
        query_ids=tuple(sorted({item.row.query_id for item in items})),
        impressions=sum(item.row.impressions for item in items),
        clicks=sum(item.row.clicks for item in items),
        cost=sum((item.row.cost for item in items), Decimal("0")),
        conversions=sum((item.row.conversions for item in items), Decimal("0")),
    )
