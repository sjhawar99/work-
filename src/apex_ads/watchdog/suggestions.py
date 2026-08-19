"""Candidate negative keywords, and the collision gate they must pass (spec §13.5).

Suggestions are **never applied**. They are candidates a human pastes into `03 KEYWORDS`
if they agree, after which the next compiler run enforces them. That is the whole safety
model: the Watchdog proposes into the workbook, and the workbook is the only thing that
reaches the account.

The dangerous arrow here is *finding → suggestion*. A negative that removes junk and also
blocks a keyword Apex pays for is not a smaller win — it is a loss, and it is invisible in
the Google Ads interface. So every candidate goes through **the compiler's own collision
engine**, at the scope it would actually be created at. A candidate that would block a
current positive is not emitted as a suggestion at all; it becomes a `ROUTING_CONFLICT`
row explaining the tension, for a person to resolve.

Three rules govern the text and level, in order (spec §13.5):

1. narrowest text that removes the problem — the offending token before the whole query;
2. lowest sufficient level — ad group before campaign before account;
3. `PHRASE` for multi-token text, `EXACT` when the entire query is the problem.

Every suggestion carries the evidence it was derived from, so a human can judge it without
re-running anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apex_ads.models.config import Rules
from apex_ads.models.workbook import Keyword
from apex_ads.util.text import tokenise
from apex_ads.validate.collisions import matches
from apex_ads.watchdog.findings import Analysed, FindingType
from apex_ads.watchdog.taxonomy import Category, Taxonomy

SUGGESTION = "SUGGESTION"
ROUTING_CONFLICT = "ROUTING_CONFLICT"

ACCOUNT = "ACCOUNT"
CAMPAIGN = "CAMPAIGN"
AD_GROUP = "AD_GROUP"


@dataclass(frozen=True)
class Candidate:
    """A proposed negative, or the conflict that stopped it becoming one."""

    status: str
    """`SUGGESTION` or `ROUTING_CONFLICT`. Never anything that reads as "applied"."""
    text: str
    match_type: str
    level: str
    scope: str
    reason: str
    blocked_query_ids: tuple[str, ...]
    impressions: int
    clicks: int
    cost: Decimal
    conversions: Decimal
    conflicts_with: tuple[str, ...] = ()
    """Positive keywords this candidate would block. Non-empty exactly when the status is
    `ROUTING_CONFLICT`."""

    def as_record(self) -> dict[str, str]:
        return {
            "status": self.status,
            "negative_text": self.text,
            "match_type": self.match_type,
            "level": self.level,
            "scope": self.scope,
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
    """What one candidate text would have removed last period."""

    query_ids: tuple[str, ...]
    impressions: int
    clicks: int
    cost: Decimal
    conversions: Decimal


def _offending_tokens(item: Analysed, taxonomy: Taxonomy) -> list[str]:
    """The narrowest text that removes the problem.

    The tokens the classifier itself matched on — not the whole query. Blocking
    `paralysis treatment cost in jaipur` removes one query; blocking the junk token that
    made it junk removes the family it belongs to.
    """
    matched = [token for token in item.classification.matched if ":" not in token]
    return [token for token in matched if token]


def _match_type(text: str, whole_query: bool) -> str:
    if whole_query:
        return "EXACT"
    return "PHRASE" if len(tokenise(text)) > 1 else "BROAD"


def _level_and_scope(item: Analysed, category: Category) -> tuple[str, str]:
    """Lowest sufficient level.

    Junk vocabulary is account-wide because the word is wrong everywhere. A specialty leak
    is wrong only in the campaign it leaked into, so it is scoped there — blocking it
    account-wide would also block the specialty that legitimately owns it.
    """
    if category is Category.JUNK_VOCABULARY:
        return ACCOUNT, "Account"
    if category is Category.COMPETITOR:
        return ACCOUNT, "Account"
    if item.row.ad_group:
        return AD_GROUP, f"{item.row.campaign} / {item.row.ad_group}"
    return CAMPAIGN, item.row.campaign


def _conflicts(
    text: str, match_type: str, level: str, scope: str, positives: list[Keyword]
) -> list[str]:
    """Positive keywords this candidate would block, **within the scope it would apply**.

    Scope-aware, exactly like `NEG-*`: an ad-group negative that would block a keyword in a
    different campaign is not a conflict, and reporting it as one produces the wall of
    false blockers that teaches people to stop reading the report.
    """
    blocked: list[str] = []
    for keyword in positives:
        if not keyword.text:
            continue
        if level == CAMPAIGN and keyword.campaign != scope:
            continue
        if level == AD_GROUP and str(keyword.key) != scope:
            continue
        if matches(text, match_type, keyword.text):
            blocked.append(f"{keyword.text} ({keyword.match_type.lower()}) in {keyword.key}")
    return blocked


def build(
    analysed: list[Analysed], taxonomy: Taxonomy, positives: list[Keyword], rules: Rules
) -> list[Candidate]:
    """Propose negatives for JUNK, competitor BRAND_LEAK and SPECIALTY_LEAK findings."""
    proposals: dict[tuple[str, str, str, str], list[Analysed]] = {}
    reasons: dict[tuple[str, str, str, str], str] = {}

    for item in analysed:
        kinds = {finding.type for finding in item.findings}
        category = item.classification.category

        # Spec §13.5 names three sources: JUNK, **competitor** BRAND_LEAK, and
        # SPECIALTY_LEAK. Own-brand leak is deliberately excluded, and this is the most
        # important line in the module.
        #
        # A brand term served by the wrong campaign is a ROUTING problem: the fix is to
        # cover it in the brand campaign, not to negate it. Treating it as a suggestion
        # source produced `negative: "apex" (broad)` — a proposal to stop bidding on Apex's
        # own name — with no collision to stop it, because the Neuro ad group has no
        # `apex` positive to collide with. It is in routing_issues.csv instead, where the
        # remedy is the one that helps.
        eligible = {
            kind
            for kind in kinds
            if kind is FindingType.SPECIALTY_LEAK
            or (kind is FindingType.JUNK and category is Category.JUNK_VOCABULARY)
            or (kind is FindingType.BRAND_LEAK and category is Category.COMPETITOR)
        }
        if not eligible:
            continue

        # Only vocabulary-backed findings produce text we can defend. Statistical junk —
        # impressions with no clicks — is ranked for review but never auto-worded into a
        # negative: "this got no clicks" is not evidence about which word was wrong.
        tokens = _offending_tokens(item, taxonomy)
        if not tokens:
            continue

        # And never propose negating our own vocabulary, or a function word, whatever
        # produced the finding. Both are already excluded upstream — `brand_tokens` from
        # suggestion eligibility, stopwords from distinctive tokens — so this is defence in
        # depth for a proposal that would be catastrophic rather than merely wrong:
        # `negative: in (broad)` blocks nearly every query in the account.
        tokens = [
            token
            for token in tokens
            if token not in taxonomy.brand_tokens and token not in taxonomy.stopword_tokens
        ]
        if not tokens:
            continue

        level, scope = _level_and_scope(item, category)
        for token in tokens:
            match_type = _match_type(token, whole_query=False)
            key = (token, match_type, level, scope)
            proposals.setdefault(key, []).append(item)
            reasons.setdefault(
                key,
                f"{sorted(kind.value for kind in eligible)[0]} — matched {token!r}",
            )

    candidates: list[Candidate] = []
    for (text, match_type, level, scope), items in proposals.items():
        evidence = _evidence(items)
        conflicts = _conflicts(text, match_type, level, scope, positives)
        candidates.append(
            Candidate(
                status=ROUTING_CONFLICT if conflicts else SUGGESTION,
                text=text,
                match_type=match_type,
                level=level,
                scope=scope,
                reason=(
                    reasons[(text, match_type, level, scope)]
                    if not conflicts
                    else (
                        f"{reasons[(text, match_type, level, scope)]}; NOT SUGGESTED — it "
                        f"would block {len(conflicts)} positive keyword(s) we pay for"
                    )
                ),
                blocked_query_ids=evidence.query_ids,
                impressions=evidence.impressions,
                clicks=evidence.clicks,
                cost=evidence.cost,
                conversions=evidence.conversions,
                conflicts_with=tuple(conflicts),
            )
        )

    candidates.sort(key=lambda candidate: (-candidate.cost, candidate.text, candidate.scope))
    return candidates


def _evidence(items: list[Analysed]) -> Evidence:
    return Evidence(
        query_ids=tuple(sorted({item.row.query_id for item in items})),
        impressions=sum(item.row.impressions for item in items),
        clicks=sum(item.row.clicks for item in items),
        cost=sum((item.row.cost for item in items), Decimal("0")),
        conversions=sum((item.row.conversions for item in items), Decimal("0")),
    )
