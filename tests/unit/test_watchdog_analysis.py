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
from apex_ads.watchdog.routing import CoverageStatus, coverage_for, positives
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
    assert any(pattern.text == "job" for pattern in vocabulary.junk_patterns)


def test_negatives_keep_their_match_type_and_list(vocabulary: taxonomy.Taxonomy) -> None:
    """Each approved negative survives whole, with the list that gives it its reach."""
    assert vocabulary.junk_patterns
    for pattern in vocabulary.junk_patterns:
        assert pattern.match_type in {"EXACT", "PHRASE", "BROAD"}
        assert pattern.list_name
        assert pattern.level in {"ACCOUNT", "SHARED_LIST"}


def test_a_multiword_negative_is_never_exploded_into_tokens(
    bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The defect that classified the brand's own core term as COMPETITOR.

    `ck birla hospital` (phrase) was exploded to `{ck, birla, hospital}`, so any query
    containing `hospital` matched — including `apex hospital jaipur`. A suggestion derived
    from that token would have proposed an account-wide broad negative on `hospital`.
    """

    existing = bundle.negatives[0]
    competitor = existing.model_copy(
        update={
            "text": "ck birla hospital",
            "match_type": "PHRASE",
            "list_name": "ROUTE_COMPETITORS",
        }
    )
    with_competitor = bundle.model_copy(update={"negatives": [*bundle.negatives, competitor]})
    vocabulary = taxonomy.build(with_competitor, watchdog_config.rules)

    # the whole phrase matches
    assert (
        vocabulary.classify(term("ck birla hospital jaipur", query_key)).category
        is Category.COMPETITOR
    )
    # one of its words does not
    for innocent in ("apex hospital jaipur", "best hospital in jaipur", "hospital"):
        assert vocabulary.classify(term(innocent, query_key)).category is not Category.COMPETITOR, (
            innocent
        )


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
    assert any("job" in label for label in result.matched)
    assert result.patterns and result.patterns[0].text == "job"
    assert result.heuristic is False, "an approved negative is a decision, not a heuristic"


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


def test_coverage_comes_from_the_export_not_from_an_offline_matcher(
    bundle, query_key: QueryIdKey
) -> None:
    """Google names the keyword that triggered each row. That is the answer; we read it.

    The previous version of this test asserted that phrase coverage requires a literal
    contiguous run — because that is how `validate.collisions.matches()` behaves. That
    engine implements *negative* semantics. Google positive phrase and exact matching
    consider meaning and apply close variants, so the old test locked in a matcher that
    systematically under-reports coverage, and every `HELD_DEMAND` built on it was suspect.
    """
    keywords = positives(bundle)

    approved = coverage_for(term("anything at all", query_key), "apex hospital", "Exact", keywords)
    assert approved.status is CoverageStatus.APPROVED
    assert approved.owners

    unknown_keyword = coverage_for(
        term("anything at all", query_key), "keyword nobody approved", "Phrase", keywords
    )
    assert unknown_keyword.status is CoverageStatus.NOT_IN_WORKBOOK

    # And when the export names nothing, the answer is UNKNOWN — never "not covered".
    silent = coverage_for(term("anything at all", query_key), "", "", keywords)
    assert silent.status is CoverageStatus.UNKNOWN


def test_there_is_no_offline_positive_matcher_to_misuse() -> None:
    """The method that caused this is gone by name, not merely unused.

    `matched_by` was documented as "Google's semantics" and used for positive coverage.
    It is now `matched_by_negative`, which is what it always was.
    """
    from apex_ads.util.searchterm import SearchTerm as Term

    assert not hasattr(Term, "matched_by")
    assert hasattr(Term, "matched_by_negative")


def test_held_demand_is_an_identity_test_against_the_workbook(
    bundle, query_key: QueryIdKey
) -> None:
    """ "The workbook has no keyword of its own for this query" — a fact, not a match."""
    keywords = positives(bundle)
    known = coverage_for(term("apex hospital", query_key), "apex hospital", "Exact", keywords)
    assert known.has_own_keyword

    novel = coverage_for(
        term("paralysis treatment cost jaipur", query_key), "apex hospital", "Exact", keywords
    )
    assert not novel.has_own_keyword


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


def test_a_specialty_leak_produces_no_negative_at_all(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Its only defensible texts are an unapproved token or the patient's own words.

    The first version proposed the matched specialty token as a broad negative — a
    transformation nobody approved. The remedy for a term served by the wrong campaign is
    routing, and `routing_issues.csv` says so.
    """
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    _analysed, found = analyse(export, bundle, watchdog_config)
    assert any(f.type is FindingType.SPECIALTY_LEAK for f in found), "fixture must leak"

    candidates = _candidates(exports, bundle, watchdog_config, query_key)
    assert all(candidate.text != "neurologist" for candidate in candidates), [
        c.text for c in candidates
    ]


def test_every_candidate_text_is_an_already_approved_negative(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Nothing here invents a negative, and nothing derives one from a token."""
    approved = {negative.text for negative in bundle.negatives if negative.text}
    for candidate in _candidates(exports, bundle, watchdog_config, query_key):
        assert candidate.text in approved, candidate.text


def test_a_competitor_candidate_keeps_its_approved_list_and_reach(
    bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """`ROUTE_COMPETITORS` excludes Brand deliberately; an account negative would not.

    Sending competitor suggestions to ACCOUNT widened approved policy, and the writeback
    then relabelled them `ACCOUNT_JUNK` — so the same term returned next Friday classified
    as junk rather than competitor.
    """

    from apex_ads.models.config import SharedList

    # The fixture account keeps only ROUTE_BRAND; give it the competitor list at fixture
    # scale, with Brand excluded exactly as the real config excludes it.
    reach = ["TST | Search | Neuro | Jaipur"]
    negatives_rules = watchdog_config.rules.negatives.model_copy(
        update={
            "shared_lists": {
                **watchdog_config.rules.negatives.shared_lists,
                "ROUTE_COMPETITORS": SharedList(applies_to=reach),
            }
        }
    )
    rules = watchdog_config.rules.model_copy(update={"negatives": negatives_rules})

    existing = bundle.negatives[0]
    competitor = existing.model_copy(
        update={"text": "rival clinic", "match_type": "PHRASE", "list_name": "ROUTE_COMPETITORS"}
    )
    with_competitor = bundle.model_copy(update={"negatives": [*bundle.negatives, competitor]})
    vocabulary = taxonomy.build(with_competitor, rules)
    pattern = next(p for p in vocabulary.competitor_patterns if p.text == "rival clinic")

    assert pattern.list_name == "ROUTE_COMPETITORS"
    assert pattern.level == "SHARED_LIST"
    assert pattern.reach == tuple(reach)
    assert "TST | Search | Brand | Jaipur" not in pattern.reach, (
        "the approved list excludes Brand; an ACCOUNT-level negative would not"
    )


def test_a_candidate_never_widens_to_the_account(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """A candidate's level is its list's own kind, never a scope chosen at suggestion time."""
    vocabulary = taxonomy.build(bundle, watchdog_config.rules)
    by_text = {p.text: p for p in (*vocabulary.junk_patterns, *vocabulary.competitor_patterns)}
    for candidate in _candidates(exports, bundle, watchdog_config, query_key):
        pattern = by_text[candidate.text]
        assert candidate.level == pattern.level
        assert candidate.destination_list == pattern.list_name
        assert candidate.executable_reach == pattern.reach


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

    keywords = positives(bundle)
    # A positive containing the approved junk word `job`, in the campaign that served it.
    collide = keywords[0].model_copy(
        update={
            "text": "hospital job openings",
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

    A shared-list candidate must only consider positives in the campaign it would newly
    reach, not every positive in the account.
    """
    from apex_ads.watchdog.taxonomy import NegativePattern

    keywords = positives(bundle)
    elsewhere = keywords[0].model_copy(
        update={
            "text": "rival clinic reviews",
            "match_type": "PHRASE",
            "campaign": "TST | Search | Neuro | Jaipur",
            "ad_group": "Neuro | Provider",
        }
    )
    pattern = NegativePattern(
        text="rival clinic",
        match_type="PHRASE",
        list_name="ROUTE_COMPETITORS",
        level="SHARED_LIST",
        reach=("TST | Search | Neuro | Jaipur",),
    )
    # The incident is in Brand; the colliding positive is in Neuro, which this candidate
    # would not newly reach.
    assert not suggestions._conflicts(
        pattern, "TST | Search | Brand | Jaipur", [*keywords, elsewhere]
    )
    # In the campaign it would reach, the same positive is a real conflict.
    assert suggestions._conflicts(pattern, "TST | Search | Neuro | Jaipur", [*keywords, elsewhere])


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


# ------------------------------------------- an aggregate needs a complete denominator


def test_a_parse_error_withholds_the_spend_share_for_that_campaign(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Row-level evidence survives a parse error. An aggregate does not.

    `concentration()` divided each query's cost by the sum of only the *readable* rows, so
    one unreadable expensive row turned a genuine 25% into a printed 70% — and nothing
    about the output looked wrong. The absolute cost is still reported; the percentage is
    refused, the same discipline `UNKNOWN` gets everywhere else.
    """
    export = read_export(exports["parse_errors"], watchdog_config.rules.watchdog, query_key)
    assert export.parse_errors, "fixture must contain unreadable rows"

    damaged = export.incomplete_campaigns()
    assert damaged

    analysed, found = analyse(export, bundle, watchdog_config)
    shares = [f for f in found if f.type is FindingType.CONCENTRATION]
    assert shares

    for finding in shares:
        row = next(item.row for item in analysed if item.row.query_id == finding.query_id)
        if row.campaign in damaged:
            assert "NOT COMPUTED" in finding.detail, finding.detail
            assert "%" not in finding.detail
        else:
            assert "%" in finding.detail


def test_a_clean_export_still_computes_shares(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The suppression must be caused by the parse error, not by being switched off."""
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    assert not export.parse_errors
    assert export.incomplete_campaigns() == frozenset()
    _, found = analyse(export, bundle, watchdog_config)
    shares = [f for f in found if f.type is FindingType.CONCENTRATION]
    assert shares
    assert all("%" in finding.detail for finding in shares)


def test_an_unattributable_parse_error_poisons_every_denominator(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """A short row may have no readable campaign cell. Then no total can be trusted."""
    export = read_export(exports["parse_errors"], watchdog_config.rules.watchdog, query_key)
    unattributed = [error for error in export.parse_errors if not error.campaign]
    assert unattributed, "the short-row fixture has no readable campaign"
    assert export.incomplete_campaigns() == frozenset(row.campaign for row in export.rows)
