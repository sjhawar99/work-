"""Classifying a search term against the workbook's own taxonomy (spec §13.2).

**The taxonomy is derived from the workbook, not written in config.** Which words mean
"Neuro" at Apex is an approved account decision that already exists in `03 KEYWORDS`; a
second copy in `rules.yaml` would be a second answer to a question that already has one,
which is the shape of bug this project keeps finding. Config holds only the structural
vocabulary that is not an Apex decision — the intent modifiers Google users type
(`cost`, `near me`, `doctor`) and which negative lists mean "junk" and "competitor".

Derivation, in order:

1. **Campaign names decode themselves.** `MLN | Search | Neuro | Jaipur` yields
   specialty `Neuro` and city `Jaipur`, using the naming pattern the compiler already
   enforces (`STR-001`). No new source of truth.
2. **Distinctive tokens per specialty.** The normalised tokens of a campaign's positive
   keywords, minus tokens that appear in more than one campaign, minus geo and intent
   modifiers. A token shared by three campaigns identifies none of them, so it is
   discarded rather than assigned to whichever campaign is read first.
3. **Brand and competitor vocabulary** come from the negative lists named in config —
   the workbook already lists competitor names as negatives, and duplicating them here
   would be a third copy.

`classify()` returns `CLASSIFIER_UNRESOLVED` for anything it cannot resolve, and that is
a feature. An honest "I don't know" list is more useful than a confident wrong bucket, and
it is how the taxonomy improves: the unresolved list is what a human reads on Friday.

Nothing here reads a threshold. Classification is deterministic set membership.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from apex_ads.models.config import Rules
from apex_ads.models.identity import AdGroupKey
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.util.searchterm import SearchTerm
from apex_ads.util.text import tokenise


class Category(str, Enum):
    """What a search term is, as far as the workbook can say."""

    BRAND = "BRAND"
    COMPETITOR = "COMPETITOR"
    SPECIALTY = "SPECIALTY"
    JUNK_VOCABULARY = "JUNK_VOCABULARY"
    UNRESOLVED = "CLASSIFIER_UNRESOLVED"


@dataclass(frozen=True)
class NegativePattern:
    """One approved negative, kept whole: text, match type, list and reach.

    Whole because the previous version exploded every negative into tokens and treated any
    single token as a match. `ck birla hospital` (phrase) became `{ck, birla, hospital}`,
    and `apex hospital jaipur` — the brand's own core term — then classified as
    COMPETITOR on the token `hospital`. A phrase negative means the phrase, in order; a
    token from it means nothing on its own, and a suggestion derived from that token would
    have proposed an account-wide broad negative on `hospital`.
    """

    text: str
    match_type: str
    list_name: str
    level: str
    """`ACCOUNT` or `SHARED_LIST` — where the approved policy puts this list."""
    reach: tuple[str, ...]
    """The campaigns this list actually reaches, from `rules.negatives`. `()` with
    `level == "ACCOUNT"` means every campaign."""

    def reaches(self, campaign: str) -> bool:
        return True if self.level == "ACCOUNT" else campaign in self.reach

    def label(self) -> str:
        return f"{self.text} ({self.match_type.lower()}, {self.list_name})"


@dataclass(frozen=True)
class Classification:
    """One term's classification, with the evidence that produced it."""

    category: Category
    specialty: str | None
    """The specialty segment of the campaign this term belongs to, when known."""
    matched: tuple[str, ...]
    """What decided it, printed so a human can disagree.

    For vocabulary categories these are approved negative *patterns* (`label()`), never
    loose tokens. For the specialty heuristic they are tokens, and `heuristic` is True.
    """
    patterns: tuple[NegativePattern, ...] = ()
    """The approved negatives that matched. The only legitimate source of a suggestion."""
    heuristic: bool = False
    """True when the category came from the distinctive-token heuristic rather than from
    an approved negative. A heuristic may inform routing; it may never author a negative."""

    @property
    def resolved(self) -> bool:
        return self.category is not Category.UNRESOLVED


def campaign_specialty(name: str) -> str | None:
    """`MLN | Search | Neuro | Jaipur` → `Neuro`. The name already carries it."""
    parts = [part.strip() for part in name.split("|")]
    return parts[2] if len(parts) >= 4 else None


def campaign_city(name: str) -> str | None:
    parts = [part.strip() for part in name.split("|")]
    return parts[3] if len(parts) >= 4 else None


@dataclass
class Taxonomy:
    """The workbook's own vocabulary, indexed for classification."""

    specialty_tokens: dict[str, frozenset[str]] = field(default_factory=dict)
    """Specialty → tokens distinctive to it."""
    brand_tokens: frozenset[str] = frozenset()
    competitor_patterns: tuple[NegativePattern, ...] = ()
    junk_patterns: tuple[NegativePattern, ...] = ()
    geo_tokens: frozenset[str] = frozenset()
    modifier_tokens: frozenset[str] = frozenset()
    stopword_tokens: frozenset[str] = frozenset()
    specialty_of_campaign: dict[str, str] = field(default_factory=dict)
    ad_groups_of_specialty: dict[str, tuple[AdGroupKey, ...]] = field(default_factory=dict)
    discarded_ambiguous: frozenset[str] = frozenset()
    """Tokens seen in more than one campaign, kept only so the report can say why a term
    went unresolved rather than leaving it looking arbitrary."""

    def classify(self, term: SearchTerm) -> Classification:
        """Deterministic, precedence-ordered set membership. Never a guess.

        Takes the protected `SearchTerm` and asks it which of *our* words appear, rather
        than reading the query. The classifier therefore never holds the patient's
        sentence — only the subset of the workbook's own vocabulary that occurred in it.
        """
        if not term.token_count():
            return Classification(Category.UNRESOLVED, None, ())

        # Precedence, documented and fixed:
        #   competitor > junk vocabulary > brand > specialty
        #
        # The two explicit human lists come first, because a negative somebody deliberately
        # approved is a decision, while a brand or specialty token is *inferred* from the
        # keyword table. Brand-before-junk had this backwards: `apex hospital job`
        # classified as BRAND and raised no JUNK finding, because our own name outranked
        # the word that made the query worthless.
        #
        # Competitor before junk because a competitor comparison is the more specific and
        # more expensive finding of the two.
        #
        # Both use the NEGATIVE matcher on the whole approved pattern. A phrase negative
        # matches its phrase, in order; it does not match one of its words.
        competitor = self._matching(term, self.competitor_patterns)
        if competitor:
            return Classification(
                Category.COMPETITOR,
                None,
                tuple(pattern.label() for pattern in competitor),
                patterns=competitor,
            )

        junk = self._matching(term, self.junk_patterns)
        if junk:
            return Classification(
                Category.JUNK_VOCABULARY,
                None,
                tuple(pattern.label() for pattern in junk),
                patterns=junk,
            )

        brand = term.intersect(self.brand_tokens)
        if brand:
            return Classification(Category.BRAND, "Brand", tuple(sorted(brand)), heuristic=True)

        hits = {
            specialty: found
            for specialty, distinctive in self.specialty_tokens.items()
            if (found := term.intersect(distinctive))
        }
        if len(hits) == 1:
            specialty, matched = next(iter(hits.items()))
            return Classification(
                Category.SPECIALTY, specialty, tuple(sorted(matched)), heuristic=True
            )
        if len(hits) > 1:
            # Two specialties both claim it. Refusing is the honest answer: picking the
            # one with more matching tokens would be inventing a rule nobody approved.
            return Classification(
                Category.UNRESOLVED,
                None,
                tuple(
                    sorted(f"{specialty}:{'+'.join(sorted(m))}" for specialty, m in hits.items())
                ),
                heuristic=True,
            )
        return Classification(Category.UNRESOLVED, None, ())

    @staticmethod
    def _matching(
        term: SearchTerm, patterns: tuple[NegativePattern, ...]
    ) -> tuple[NegativePattern, ...]:
        """Approved negatives that would actually block this query, whole pattern intact."""
        return tuple(
            pattern
            for pattern in patterns
            if term.matched_by_negative(pattern.text, pattern.match_type)
        )


def build(bundle: WorkbookBundle, rules: Rules) -> Taxonomy:
    """Derive the taxonomy from the workbook this run is validating against."""
    settings = rules.watchdog.taxonomy

    specialty_of_campaign: dict[str, str] = {}
    geo: set[str] = set()
    for campaign in bundle.campaigns:
        specialty = campaign_specialty(campaign.name)
        if specialty:
            specialty_of_campaign[campaign.name] = specialty
        city = campaign_city(campaign.name)
        if city:
            geo.update(tokenise(city))
    geo.update(token for value in settings.geo_terms for token in tokenise(value))

    modifiers = {token for value in settings.intent_modifiers for token in tokenise(value)}
    stopwords = {token for value in settings.stopwords for token in tokenise(value)}

    # Token → the specialties whose positive keywords contain it.
    owners: dict[str, set[str]] = defaultdict(set)
    for keyword in bundle.keywords:
        specialty = specialty_of_campaign.get(keyword.campaign or "")
        if not specialty:
            continue
        for token in tokenise(keyword.text):
            owners[token].add(specialty)

    ignore = geo | modifiers | stopwords
    distinctive: dict[str, set[str]] = defaultdict(set)
    ambiguous: set[str] = set()
    for token, specialties in owners.items():
        if token in ignore:
            continue
        if len(specialties) > 1:
            ambiguous.add(token)
            continue
        distinctive[next(iter(specialties))].add(token)

    brand_label = settings.brand_specialty_label
    brand = frozenset(distinctive.pop(brand_label, set()))

    groups: dict[str, list[AdGroupKey]] = defaultdict(list)
    for group in bundle.ad_groups:
        specialty = specialty_of_campaign.get(group.campaign)
        if specialty:
            groups[specialty].append(group.key)

    return Taxonomy(
        specialty_tokens={
            specialty: frozenset(tokens) for specialty, tokens in distinctive.items() if tokens
        },
        brand_tokens=brand,
        competitor_patterns=_patterns_from_lists(bundle, rules, settings.competitor_lists),
        junk_patterns=_patterns_from_lists(bundle, rules, settings.junk_lists),
        geo_tokens=frozenset(geo),
        modifier_tokens=frozenset(modifiers),
        stopword_tokens=frozenset(stopwords),
        specialty_of_campaign=specialty_of_campaign,
        ad_groups_of_specialty={
            specialty: tuple(sorted(keys, key=str)) for specialty, keys in groups.items()
        },
        discarded_ambiguous=frozenset(ambiguous),
    )


def _patterns_from_lists(
    bundle: WorkbookBundle, rules: Rules, list_names: list[str]
) -> tuple[NegativePattern, ...]:
    """Approved negatives from the named lists, each kept whole with its approved reach.

    The workbook carries competitor names and junk words as negatives; config says which
    campaigns each list reaches. Both are read here so neither can be restated — and so a
    suggestion derived from one of these patterns inherits the reach its own list was
    approved with, rather than being widened to the account.
    """
    wanted = {name.strip().casefold() for name in list_names}
    account = {name.strip().casefold() for name in rules.negatives.account_lists}
    reach = {
        name.strip().casefold(): tuple(shared.applies_to)
        for name, shared in rules.negatives.shared_lists.items()
    }

    patterns: list[NegativePattern] = []
    for negative in bundle.negatives:
        name = (negative.list_name or "").strip()
        folded = name.casefold()
        if folded not in wanted or not negative.text:
            continue
        patterns.append(
            NegativePattern(
                text=negative.text,
                match_type=negative.match_type,
                list_name=name,
                level="ACCOUNT" if folded in account else "SHARED_LIST",
                reach=reach.get(folded, ()),
            )
        )
    return tuple(patterns)
