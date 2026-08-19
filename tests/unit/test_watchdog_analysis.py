"""Taxonomy, routing, findings and suggestions (spec §13.2-§13.5).

These test the chain the reviewer named:

    classification → expected routing → actual routing → finding → negative suggestion

Every bug this project has found lived where one of those arrows quietly changed meaning,
so each test names the arrow it is holding still.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import Config, WorkbookSchema
from apex_ads.util.queryid import QueryIdKey
from apex_ads.util.searchterm import SearchTerm
from apex_ads.watchdog import suggestions, taxonomy
from apex_ads.watchdog.findings import FLAGGED, REVIEW, FindingType
from apex_ads.watchdog.ingest import read_export
from apex_ads.watchdog.routing import coverage_for, positives
from apex_ads.watchdog.run import analyse
from apex_ads.watchdog.taxonomy import Category


@pytest.fixture()
def bundle(fixtures: dict[str, Path], schema: WorkbookSchema):
    return parse_workbook(fixtures["clean"], schema)


@pytest.fixture()
def vocabulary(bundle, watchdog_config: Config) -> taxonomy.Taxonomy:
    return taxonomy.build(bundle, watchdog_config.rules)


def term(text: str, key: QueryIdKey) -> SearchTerm:
    return SearchTerm(text, source_file="t.csv", row=1, key=key)


# ------------------------------------------------------------------ taxonomy


def test_the_taxonomy_is_derived_from_the_workbook(vocabulary: taxonomy.Taxonomy) -> None:
    """Not written in config: a second copy would be a second answer."""
    assert "neurologist" in vocabulary.specialty_tokens.get("Neuro", frozenset())
    assert "apex" in vocabulary.brand_tokens
    assert "job" in vocabulary.junk_tokens


def test_a_token_shared_by_two_campaigns_identifies_neither(
    vocabulary: taxonomy.Taxonomy,
) -> None:
    """`hospital` cannot mean Neuro because Neuro's keywords happen to contain it."""
    for specialty, tokens in vocabulary.specialty_tokens.items():
        assert not (tokens & vocabulary.discarded_ambiguous), specialty


def test_stopwords_are_never_distinctive(vocabulary: taxonomy.Taxonomy) -> None:
    """`neurologist in jaipur` made `in` distinctive to Neuro, and the Watchdog then
    proposed `negative: in (broad)` — which would block nearly every query in the account."""
    for tokens in vocabulary.specialty_tokens.values():
        assert "in" not in tokens
    assert "in" in vocabulary.stopword_tokens


def test_geo_and_intent_modifiers_are_not_specialty_signals(
    vocabulary: taxonomy.Taxonomy,
) -> None:
    for tokens in vocabulary.specialty_tokens.values():
        assert not (tokens & vocabulary.geo_tokens)
        assert not (tokens & vocabulary.modifier_tokens)


def test_an_unknown_term_is_unresolved_not_forced_into_a_bucket(
    vocabulary: taxonomy.Taxonomy, query_key: QueryIdKey
) -> None:
    """An honest "I don't know" list is more useful than a confident wrong bucket."""
    result = vocabulary.classify(term("zzz unknown phrase here", query_key))
    assert result.category is Category.UNRESOLVED
    assert not result.resolved


def test_junk_vocabulary_outranks_our_own_brand(
    vocabulary: taxonomy.Taxonomy, query_key: QueryIdKey
) -> None:
    """`apex hospital job` is junk, not a brand win.

    Brand-before-junk had this backwards: our own name outranked the word that made the
    query worthless, and the JUNK finding never fired.
    """
    result = vocabulary.classify(term("apex hospital job", query_key))
    assert result.category is Category.JUNK_VOCABULARY
    assert "job" in result.matched


def test_two_specialties_claiming_a_term_refuses_rather_than_picking(
    bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Picking the one with more matching tokens would be inventing a rule nobody approved."""
    forced = taxonomy.Taxonomy(
        specialty_tokens={"Neuro": frozenset({"scan"}), "Ortho": frozenset({"scan2"})},
    )
    result = forced.classify(term("scan scan2", query_key))
    assert result.category is Category.UNRESOLVED
    assert len(result.matched) == 2


# ------------------------------------------------------------------- routing


def test_coverage_uses_the_compilers_own_match_engine(bundle, query_key: QueryIdKey) -> None:
    """`EXACT` must mean the same thing to the Watchdog as to the collision check."""
    keywords = positives(bundle)
    assert coverage_for(term("apex hospital", query_key), keywords).covered
    # phrase needs the contiguous run: "neurologist in jaipur" does not occur here
    assert not coverage_for(term("neurologist jaipur", query_key), keywords).covered


def test_an_unresolved_term_never_produces_a_leak_finding(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """A guessed owner would manufacture leakage out of the classifier's own uncertainty."""
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    analysed, _ = analyse(export, bundle, watchdog_config)
    for item in analysed:
        if item.classification.category is Category.UNRESOLVED:
            assert item.routing.expected is None
            assert not item.routing.leaked


def test_a_specialty_term_served_by_another_campaign_is_leakage(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    _, found = analyse(export, bundle, watchdog_config)
    leaks = [f for f in found if f.type is FindingType.SPECIALTY_LEAK]
    assert leaks
    assert leaks[0].expected != leaks[0].actual


# ------------------------------------------------------- no invented thresholds


def test_every_null_threshold_yields_review_not_a_verdict(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """`null` means "we do not know yet". The honest implementation shows the evidence."""
    thresholds = watchdog_config.rules.watchdog.thresholds
    assert all(value is None for value in thresholds.model_dump().values()), (
        "Stage 1 must ship with every threshold null"
    )

    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    _, found = analyse(export, bundle, watchdog_config)

    graded = [f for f in found if f.type is not FindingType.JUNK]
    assert graded
    assert all(f.verdict == REVIEW for f in graded), [f.verdict for f in graded]


def test_vocabulary_junk_is_flagged_because_a_human_already_decided(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The one FLAGGED case, and it involves no statistical judgement at all."""
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    _, found = analyse(export, bundle, watchdog_config)
    flagged = [f for f in found if f.type is FindingType.JUNK and f.verdict == FLAGGED]
    assert flagged
    assert "negative list" in flagged[0].detail


def test_concentration_ranks_and_decides_nothing(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    _, found = analyse(export, bundle, watchdog_config)
    rows = [f for f in found if f.type is FindingType.CONCENTRATION]
    assert rows
    assert all(row.verdict == REVIEW for row in rows)
    assert rows == sorted(rows, key=lambda row: -row.cost)
    assert "%" in rows[0].detail


def test_a_set_threshold_produces_a_verdict_through_the_same_code_path(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """When a human sets a real number, only the config changes."""
    rules = watchdog_config.rules
    watchdog = rules.watchdog.model_copy(
        update={
            "thresholds": rules.watchdog.thresholds.model_copy(
                update={"held_demand_min_conversions": 1}
            )
        }
    )
    config = watchdog_config.model_copy(
        update={"rules": rules.model_copy(update={"watchdog": watchdog})}
    )
    export = read_export(exports["clean"], config.rules.watchdog, query_key)
    _, found = analyse(export, bundle, config)
    held = [f for f in found if f.type is FindingType.HELD_DEMAND]
    assert held
    assert all(f.verdict == FLAGGED for f in held)


# --------------------------------------------------------------- suggestions


def _candidates(exports, bundle, config, key):
    export = read_export(exports["clean"], config.rules.watchdog, key)
    analysed, _ = analyse(export, bundle, config)
    return suggestions.build(
        analysed, taxonomy.build(bundle, config.rules), positives(bundle), config.rules
    )


def test_suggestions_never_propose_negating_our_own_brand(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The most dangerous proposal this module could make, and it did make it.

    Own-brand leak is a ROUTING problem — cover the term in the brand campaign. Treating it
    as a suggestion source produced `negative: apex (broad)`, with no collision to stop it
    because the Neuro ad group has no `apex` positive to collide with.
    """
    vocabulary = taxonomy.build(bundle, watchdog_config.rules)
    candidates = _candidates(exports, bundle, watchdog_config, query_key)
    for candidate in candidates:
        assert candidate.text not in vocabulary.brand_tokens, candidate


def test_suggestions_never_propose_a_stopword(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    candidates = _candidates(exports, bundle, watchdog_config, query_key)
    assert all(candidate.text != "in" for candidate in candidates)


def test_a_junk_word_is_suggested_at_account_level(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The word is wrong everywhere, so the lowest sufficient level is the account."""
    candidates = _candidates(exports, bundle, watchdog_config, query_key)
    job = [c for c in candidates if c.text == "job"]
    assert job
    assert job[0].level == "ACCOUNT"
    assert job[0].status == suggestions.SUGGESTION


def test_a_specialty_leak_is_suggested_only_where_it_leaked(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Account-wide would also block the specialty that legitimately owns the term."""
    candidates = _candidates(exports, bundle, watchdog_config, query_key)
    leak = [c for c in candidates if c.text == "neurologist"]
    assert leak
    assert leak[0].level == "AD_GROUP"
    assert "Brand" in leak[0].scope


def test_every_suggestion_carries_its_evidence(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """A human must be able to judge it without re-running anything."""
    candidates = _candidates(exports, bundle, watchdog_config, query_key)
    assert candidates
    for candidate in candidates:
        assert candidate.blocked_query_ids
        assert candidate.impressions >= 0
        assert candidate.reason


def test_a_candidate_that_would_block_a_positive_becomes_a_conflict(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The gate. A negative that blocks a keyword we pay for is a loss, and invisible in
    the Google Ads interface — so it is never emitted as a suggestion."""
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    analysed, _ = analyse(export, bundle, watchdog_config)
    vocabulary = taxonomy.build(bundle, watchdog_config.rules)

    # Give the Brand ad group a positive the leak suggestion would block.
    keywords = positives(bundle)
    collide = keywords[0].model_copy(
        update={
            "text": "neurologist appointment",
            "match_type": "PHRASE",
            "campaign": "TST | Search | Brand | Jaipur",
            "ad_group": "Brand | Core",
        }
    )
    candidates = suggestions.build(
        analysed, vocabulary, [*keywords, collide], watchdog_config.rules
    )
    conflicted = [c for c in candidates if c.status == suggestions.ROUTING_CONFLICT]
    assert conflicted, [c.text for c in candidates]
    assert conflicted[0].conflicts_with
    assert "NOT SUGGESTED" in conflicted[0].reason


def test_a_conflict_is_scope_aware_not_account_blind(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """A wall of false blockers teaches everyone to stop reading the report.

    The same positive, in a campaign the candidate does not reach, must not be a conflict.
    """
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    analysed, _ = analyse(export, bundle, watchdog_config)
    vocabulary = taxonomy.build(bundle, watchdog_config.rules)
    keywords = positives(bundle)
    elsewhere = keywords[0].model_copy(
        update={
            "text": "neurologist appointment",
            "match_type": "PHRASE",
            "campaign": "TST | Search | Neuro | Jaipur",
            "ad_group": "Neuro | Provider",
        }
    )
    candidates = suggestions.build(
        analysed, vocabulary, [*keywords, elsewhere], watchdog_config.rules
    )
    leak = [c for c in candidates if c.text == "neurologist"]
    assert leak
    assert leak[0].status == suggestions.SUGGESTION, leak[0].conflicts_with


def test_statistical_junk_never_becomes_a_negative(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """ "This got no clicks" is not evidence about which word was wrong."""
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    analysed, _ = analyse(export, bundle, watchdog_config)
    unresolved_junk = [
        item
        for item in analysed
        if item.classification.category is Category.UNRESOLVED
        and any(f.type is FindingType.JUNK for f in item.findings)
    ]
    assert unresolved_junk, "the fixture must contain impressions-no-clicks on an unknown term"

    candidates = suggestions.build(
        analysed,
        taxonomy.build(bundle, watchdog_config.rules),
        positives(bundle),
        watchdog_config.rules,
    )
    ids = {qid for candidate in candidates for qid in candidate.blocked_query_ids}
    for item in unresolved_junk:
        assert item.row.query_id not in ids


def test_no_candidate_is_ever_labelled_applied(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Suggestions are not actions. The vocabulary must not drift towards implying they are."""
    candidates = _candidates(exports, bundle, watchdog_config, query_key)
    for candidate in candidates:
        assert candidate.status in {suggestions.SUGGESTION, suggestions.ROUTING_CONFLICT}
        assert "applied" not in candidate.reason.casefold()


def test_costs_are_decimal_not_float(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Money is Decimal everywhere in this project, including here."""
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    for row in export.rows:
        assert isinstance(row.cost, Decimal)
        assert isinstance(row.conversions, Decimal)
