"""What the Watchdog observed about negative policy — and never proposes changing.

## The decision this module exists to record

**Stage-1 answer: the Watchdog does not author negative policy. It observes and reports.**

That is a deliberate amendment to spec §13.5, taken consciously rather than discovered by
accident, and the spec now says so. The alternative — a Watchdog that proposes new
exclusions — needs a human-review path for text drawn from patients' own words, and that
path does not exist yet. Shipping the safer product and *naming* it is honest; shipping it
while a spec section still claims the other one is not.

So this module replaced `suggestions.py`, and the rename is the point. It emits
**observations**, never candidates, and nothing here produces a paste-ready row.

## Why the previous version was not safe

It looked safe. Every candidate's *text* was already approved, which answered the
question "can it invent a negative?" — but not the question underneath:

> **Is changing the reach of an approved list itself a policy decision?**

It is. `ROUTE_COMPETITORS` is approved against four campaigns with Brand deliberately
excluded. `NOT_REACHED` responded to a competitor term served in Brand by proposing to
extend the list into Brand — a paste-ready row that rewrote a frozen routing decision. A
shared negative list only affects the campaigns it is applied to, so extending it is a
material change to exclusion policy, not an enforcement repair.

`NOT_ENFORCED` was worse in a quieter way. Its candidate text was already in the workbook,
so its writeback row said "add `job` to `ACCOUNT_JUNK`" when `job` was already in
`ACCOUNT_JUNK`. That cannot repair anything; pasted, it makes a duplicate.

And a reach change could not have survived the next stage anyway: `NEG-008` requires
`rules.yaml`, the `03 KEYWORDS` Scope cell and the `02 BUILD` routing column to agree, and
the writeback emitted only one of the three. The proposed fix would have been blocked by
this project's own compiler.

## What is claimed now, and what is not

Two observations, both handle-only, both ending at a human:

| | what it says | what it does **not** say |
| --- | --- | --- |
| `INTENTIONAL_NON_REACH` | the list does not apply here, by design | that anything |
| | | is wrong |
| `OBSERVED_DESPITE_NEGATIVE` | an approved negative did not prevent this | that the |
| | | account is misconfigured |

**Only one of them is an action.** `INTENTIONAL_NON_REACH` is INFO and never reaches
`01_ACTIONS_append.csv`.

The reason is worth stating, because the first version got it wrong in a way that looked
responsible. A list not reaching a campaign *is* the approved policy: `ROUTE_COMPETITORS`
excludes Brand deliberately, so a competitor term served in Brand means the list did
exactly what Apex decided it should. Raising a weekly AMBER action for that asks Gaurav,
every Friday forever, whether a decision he already made still stands.

> A weekly incident becomes an action when it **contradicts** the decision. Policy behaving
> as approved is information, not a task. That is the difference between a report somebody
> reads and wallpaper.

The second wording matters. "The negative is not live in the account" was stronger than the
evidence: the Watchdog has no live account state and no change history. The query may have
served before the negative was added, the list may not be applied, the workbook may simply
be ahead of the account. Establishing which is Phase 7's job, and the report says so
instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apex_ads.models.config import Rules
from apex_ads.models.workbook import Keyword
from apex_ads.watchdog.findings import Analysed, FindingType
from apex_ads.watchdog.taxonomy import Category, NegativePattern, Taxonomy

INTENTIONAL_NON_REACH = "INTENTIONAL_NON_REACH"
OBSERVED_DESPITE_NEGATIVE = "OBSERVED_DESPITE_NEGATIVE"

ACCOUNT = "ACCOUNT"
SHARED_LIST = "SHARED_LIST"

NON_REACH_REMEDY = (
    "None. Approved policy deliberately excludes this campaign from the list, and the list "
    "behaved accordingly. Recorded so the cost is visible, not because anything is wrong."
)

DESPITE_REMEDY = (
    "Check, in this order: the export's date range against when the negative was added; "
    "whether the shared list is actually applied to this campaign in the account; whether "
    "the workbook is simply ahead of the account. Phase 7 (drift) is what answers the "
    "live-account half."
)


@dataclass(frozen=True)
class Observation:
    """One approved negative, and what was seen despite it. Never a proposal."""

    kind: str
    """`INTENTIONAL_NON_REACH` (INFO) or `OBSERVED_DESPITE_NEGATIVE` (an action)."""
    negative_text: str
    match_type: str
    list_name: str
    level: str
    approved_reach: tuple[str, ...]
    incident_campaign: str
    remedy: str
    query_ids: tuple[str, ...]
    impressions: int
    clicks: int
    cost: Decimal
    conversions: Decimal

    def as_record(self, label: str) -> dict[str, str]:
        """`label` is the negative's text, or a withholding note when it equals a query."""
        return {
            "observation": self.kind,
            "negative": label,
            "match_type": self.match_type,
            "list": self.list_name,
            "level": self.level,
            "approved_reach": ", ".join(self.approved_reach)
            or ("all campaigns" if self.level == ACCOUNT else "none"),
            "served_in": self.incident_campaign,
            "query_ids": " ".join(self.query_ids),
            "impressions": str(self.impressions),
            "clicks": str(self.clicks),
            "cost": f"{self.cost:.2f}",
            "conversions": f"{self.conversions:.2f}",
            "what_to_do": self.remedy,
        }


def build(
    analysed: list[Analysed], taxonomy: Taxonomy, positives: list[Keyword], rules: Rules
) -> list[Observation]:
    """Group what was served against the approved negatives that should have prevented it.

    `positives` and `rules` are unused and kept in the signature deliberately: the previous
    version needed them to collision-check a proposal, and their absence is the clearest
    marker that nothing here proposes anything any more.
    """
    grouped: dict[tuple[str, str, str, str], list[Analysed]] = {}
    patterns: dict[tuple[str, str, str, str], NegativePattern] = {}

    for item in analysed:
        kinds = {finding.type for finding in item.findings}
        category = item.classification.category
        relevant = (FindingType.JUNK in kinds and category is Category.JUNK_VOCABULARY) or (
            FindingType.BRAND_LEAK in kinds and category is Category.COMPETITOR
        )
        if not relevant:
            continue
        for pattern in item.classification.patterns:
            key = (pattern.text, pattern.match_type, pattern.list_name, item.row.campaign)
            grouped.setdefault(key, []).append(item)
            patterns[key] = pattern

    observations: list[Observation] = []
    for key, items in grouped.items():
        pattern = patterns[key]
        incident = key[3]
        reached = pattern.reaches(incident)
        observations.append(
            Observation(
                kind=OBSERVED_DESPITE_NEGATIVE if reached else INTENTIONAL_NON_REACH,
                negative_text=pattern.text,
                match_type=pattern.match_type,
                list_name=pattern.list_name,
                level=pattern.level,
                approved_reach=pattern.reach,
                incident_campaign=incident,
                remedy=DESPITE_REMEDY if reached else NON_REACH_REMEDY,
                query_ids=tuple(sorted({item.row.query_id for item in items})),
                impressions=sum(item.row.impressions for item in items),
                clicks=sum(item.row.clicks for item in items),
                cost=sum((item.row.cost for item in items), Decimal("0")),
                conversions=sum((item.row.conversions for item in items), Decimal("0")),
            )
        )

    observations.sort(key=lambda item: (-item.cost, item.negative_text, item.incident_campaign))
    return observations
