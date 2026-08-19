"""Expected owner vs actual owner (spec §13.4).

The arrow this module implements — *classification → expected routing → actual routing* —
is where leakage lives. A brand query served by the Generic campaign costs money twice:
once for the click at a worse price, and once because the campaign that should own it
looks smaller than it is.

## What "covered" is allowed to mean

The first version answered "does a positive keyword cover this query?" by running the
query through `validate.collisions.matches()` — the engine built for **negative** match
semantics. That is literal token containment: no close variants, no plural forms, no
meaning. Google positive matching is none of those things. Phrase and exact consider the
*meaning* of the query and apply close variants automatically, so the negative engine
systematically under-reports coverage, and every `HELD_DEMAND` built on it was suspect.

Rebuilding Google's matcher offline is not the fix; it is the same mistake with more code.
Google already answers the question. A search-terms export names the **keyword that
actually triggered** each row — that is fact, not inference, and it is what this module
now uses.

So three separate things, never conflated:

| | what it is | how it is known |
| --- | --- | --- |
| `triggering_keyword` | the keyword Google served this on | read from the export |
| `approved` | that keyword is in the workbook | set membership |
| `own_keyword` | the workbook names this exact query | normalised identity |

What the system deliberately does **not** answer: "would some other keyword in the
workbook have matched this query?" That depends on Google's semantic matching, and the
honest answer offline is `UNKNOWN`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from apex_ads.models.identity import AdGroupKey
from apex_ads.models.workbook import Keyword, WorkbookBundle
from apex_ads.util.searchterm import SearchTerm
from apex_ads.util.text import tokenise
from apex_ads.watchdog.taxonomy import Category, Classification, Taxonomy


class CoverageStatus(str, Enum):
    """How this query came to be served, as far as can be established."""

    APPROVED_HERE = "APPROVED_HERE"
    """The workbook contains this keyword, in the ad group Google says served it."""

    APPROVED_ELSEWHERE = "APPROVED_ELSEWHERE"
    """The workbook contains this keyword, but places it in a different ad group.

    Distinguished from `APPROVED_HERE` deliberately. Asking only "does any workbook keyword
    have this text?" called a live keyword approved wherever it happened to be running, so
    an ad group that had drifted read as green. The export gives campaign, ad group *and*
    keyword; the identity this project spent three phases establishing is
    `AdGroupKey(campaign, ad_group)`, and this uses it."""

    NOT_IN_WORKBOOK = "NOT_IN_WORKBOOK"
    """Triggered by a keyword the workbook does not contain — account drift, not demand."""

    UNKNOWN = "UNKNOWN"
    """The export named no triggering keyword. Never reported as either of the above."""


@dataclass(frozen=True)
class Coverage:
    """What actually served this query, and what the workbook knows about it."""

    triggering_keyword: str
    triggering_match_type: str
    served_by: AdGroupKey
    """Where Google says the keyword ran."""
    approved: tuple[Keyword, ...]
    """Workbook positives whose text is the triggering keyword. Usually zero or one."""
    own_keyword: tuple[Keyword, ...]
    """Workbook positives whose text is this exact query — an explicit-keyword test, not a
    coverage test. Named for what it is; `HELD_DEMAND` no longer uses it."""

    @property
    def status(self) -> CoverageStatus:
        if not self.triggering_keyword:
            return CoverageStatus.UNKNOWN
        if not self.approved:
            return CoverageStatus.NOT_IN_WORKBOOK
        if any(keyword.key == self.served_by for keyword in self.approved):
            return CoverageStatus.APPROVED_HERE
        return CoverageStatus.APPROVED_ELSEWHERE

    @property
    def covered(self) -> bool:
        """Did an **approved** keyword serve this query?

        This is the spec's "a positive keyword covering it", answered by the only source
        that can answer it: Google's own statement of what triggered the row. It is
        deliberately true for `APPROVED_ELSEWHERE` — the demand is covered; the *placement*
        is the separate problem.
        """
        return self.status in {CoverageStatus.APPROVED_HERE, CoverageStatus.APPROVED_ELSEWHERE}

    @property
    def has_own_keyword(self) -> bool:
        """The workbook already names this query itself. A fact, not a coverage claim."""
        return bool(self.own_keyword)

    @property
    def owners(self) -> tuple[AdGroupKey, ...]:
        """Where the workbook puts the triggering keyword."""
        seen: list[AdGroupKey] = []
        for keyword in self.approved:
            key = keyword.key
            if key is not None and key not in seen:
                seen.append(key)
        return tuple(seen)

    def describe(self) -> str:
        """Coverage in words, **without naming the keyword**.

        A triggering keyword is account configuration, not patient text — but for every
        exact-match keyword the two are the same string, so printing it into a handle-only
        artifact prints the query. This description goes into findings, the actions report
        and the dashboard; the keyword itself is a column of
        `search_term_analysis.csv`, the one artifact allowed the words, joined by query ID.
        """
        if self.status is CoverageStatus.UNKNOWN:
            return "the export named no triggering keyword"
        if self.status is CoverageStatus.APPROVED_HERE:
            return "triggered by an approved keyword, in the ad group that owns it"
        if self.status is CoverageStatus.APPROVED_ELSEWHERE:
            return "triggered by an approved keyword, but running in a different ad group"
        return "triggered by a keyword that is not in the approved workbook"


@dataclass(frozen=True)
class Routing:
    """One term's expected and actual owners, and whether they agree."""

    actual: AdGroupKey
    expected: AdGroupKey | None
    expected_specialty: str | None
    coverage: Coverage
    reason: str
    inferred: bool = False
    """True when `expected` came from the taxonomy heuristic rather than from the
    workbook's own placement of the triggering keyword. A heuristic may raise a finding
    for review; it may never be presented as Google's answer."""

    @property
    def leaked(self) -> bool:
        """True only when we can name where it should have gone and it went elsewhere."""
        if self.expected is None:
            return False
        return self.expected.campaign != self.actual.campaign


def coverage_for(
    term: SearchTerm,
    triggering: str,
    match_type: str,
    served_by: AdGroupKey,
    keywords: list[Keyword],
) -> Coverage:
    """What served this query, checked against the workbook. No offline matching.

    `triggering` comes from the export's `Keyword` column — Google's own statement of what
    served the row. Note that the export's match-type column describes how the *search
    term* matched, which can differ from the keyword's configured match type; that is why
    the keyword is looked up by text and its configured type is read from the workbook.
    """
    wanted = tokenise(triggering)
    approved = (
        tuple(keyword for keyword in keywords if keyword.text and tokenise(keyword.text) == wanted)
        if wanted
        else ()
    )
    own = tuple(keyword for keyword in keywords if keyword.text and term.has_text(keyword.text))
    return Coverage(
        triggering_keyword=triggering,
        triggering_match_type=match_type,
        served_by=served_by,
        approved=approved,
        own_keyword=own,
    )


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

    # The workbook's own placement of the keyword that actually triggered beats any
    # inference — it is where this exact keyword is approved to live.
    placed = [key for key in coverage.owners if key in candidates]
    if placed:
        return Routing(
            actual,
            placed[0],
            specialty,
            coverage,
            "the workbook places the keyword that triggered this query here",
        )

    if actual in candidates:
        return Routing(actual, actual, specialty, coverage, "already served by the right specialty")

    if len(candidates) == 1:
        return Routing(
            actual,
            candidates[0],
            specialty,
            coverage,
            f"only one ad group owns {specialty!r} (taxonomy heuristic, not Google's answer)",
            inferred=True,
        )

    # The specialty is right but which of its ad groups is a judgement call. Naming the
    # campaign is enough to call it leakage; naming an ad group would be a guess.
    return Routing(
        actual,
        AdGroupKey(campaign=_campaign_of(specialty, taxonomy), ad_group=""),
        specialty,
        coverage,
        f"specialty {specialty!r} has {len(candidates)} ad groups; campaign named, ad group "
        "not (taxonomy heuristic, not Google's answer)",
        inferred=True,
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
