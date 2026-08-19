"""Expected owner vs actual owner (spec §13.4).

The arrow this module implements — *classification → expected routing → actual routing* —
is where leakage lives. A brand query served by the Generic campaign costs money twice:
once for the click at a worse price, and once because the campaign that should own it
looks smaller than it is.

Two definitions, kept deliberately apart:

* **covered** — some positive keyword in the workbook actually matches this query, under
  Google's match semantics. Answered by the same engine the compiler uses for collisions,
  so "would this keyword match" means one thing in this project.
* **expected owner** — where the taxonomy says the query belongs. A query can be expected
  in Neuro and covered by nothing at all; that is `HELD_DEMAND`, not a routing error.

`expected` is `None` whenever the taxonomy could not resolve the term. A guessed owner
would manufacture leakage findings out of the classifier's own uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass

from apex_ads.models.identity import AdGroupKey
from apex_ads.models.workbook import Keyword, WorkbookBundle
from apex_ads.util.searchterm import SearchTerm
from apex_ads.watchdog.taxonomy import Category, Classification, Taxonomy


@dataclass(frozen=True)
class Coverage:
    """Which positive keywords, if any, actually match this query."""

    keywords: tuple[Keyword, ...]

    @property
    def covered(self) -> bool:
        return bool(self.keywords)

    @property
    def owners(self) -> tuple[AdGroupKey, ...]:
        seen: list[AdGroupKey] = []
        for keyword in self.keywords:
            key = keyword.key
            if key is not None and key not in seen:
                seen.append(key)
        return tuple(seen)


@dataclass(frozen=True)
class Routing:
    """One term's expected and actual owners, and whether they agree."""

    actual: AdGroupKey
    expected: AdGroupKey | None
    expected_specialty: str | None
    coverage: Coverage
    reason: str

    @property
    def leaked(self) -> bool:
        """True only when we can name where it should have gone and it went elsewhere."""
        if self.expected is None:
            return False
        return self.expected.campaign != self.actual.campaign


def coverage_for(term: SearchTerm, keywords: list[Keyword]) -> Coverage:
    """Every positive keyword that would match this query.

    Asked of the term itself, which answers with a boolean and keeps the words. The engine
    underneath is the compiler's, reused deliberately: `EXACT` means the same thing to the
    Watchdog as to the collision check, so a suggestion cannot be judged safe by one
    definition and dangerous by the other.
    """
    hits = tuple(
        keyword
        for keyword in keywords
        if keyword.text and term.matched_by(keyword.text, keyword.match_type)
    )
    return Coverage(keywords=hits)


def route(
    actual: AdGroupKey,
    classification: Classification,
    coverage: Coverage,
    taxonomy: Taxonomy,
) -> Routing:
    """Where this query should have been served, if that can be said at all."""
    if classification.category is Category.UNRESOLVED:
        return Routing(actual, None, None, coverage, "classifier could not resolve the term")

    if classification.category in {Category.JUNK_VOCABULARY, Category.COMPETITOR}:
        # These do not belong anywhere in the account, so "expected owner" is not a
        # question with an answer. They are findings in their own right.
        return Routing(
            actual, None, None, coverage, f"{classification.category.value} belongs nowhere"
        )

    specialty = classification.specialty
    if specialty is None:
        return Routing(actual, None, None, coverage, "no specialty for this classification")

    candidates = taxonomy.ad_groups_of_specialty.get(specialty, ())
    if not candidates:
        return Routing(
            actual, None, specialty, coverage, f"no ad group exists for specialty {specialty!r}"
        )

    # Prefer an owner that actually covers the query — a real keyword beats a taxonomy
    # inference. Fall back to the specialty's ad group only when the specialty is
    # unambiguous at ad-group level too.
    covering = [key for key in coverage.owners if key in candidates]
    if covering:
        return Routing(actual, covering[0], specialty, coverage, "a positive keyword covers it")

    if actual in candidates:
        return Routing(actual, actual, specialty, coverage, "already served by the right specialty")

    if len(candidates) == 1:
        return Routing(
            actual, candidates[0], specialty, coverage, f"only one ad group owns {specialty!r}"
        )

    # The specialty is right but which of its ad groups is a judgement call. Naming the
    # campaign is enough to call it leakage; naming an ad group would be a guess.
    return Routing(
        actual,
        AdGroupKey(campaign=_campaign_of(specialty, taxonomy), ad_group=""),
        specialty,
        coverage,
        f"specialty {specialty!r} has {len(candidates)} ad groups; campaign named, ad group not",
    )


def _campaign_of(specialty: str, taxonomy: Taxonomy) -> str:
    for campaign, found in taxonomy.specialty_of_campaign.items():
        if found == specialty:
            return campaign
    return ""


def actual_key(campaign: str, ad_group: str) -> AdGroupKey:
    return AdGroupKey(campaign=campaign, ad_group=ad_group)


def positives(bundle: WorkbookBundle) -> list[Keyword]:
    return [keyword for keyword in bundle.keywords if keyword.text]
