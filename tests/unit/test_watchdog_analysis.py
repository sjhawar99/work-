"""Taxonomy, routing, findings and observations (spec §13.2-§13.5).

These test the chain the reviewer named:

    classification → expected routing → actual routing → finding → policy observation

The last arrow used to end in a *negative suggestion*. It does not any more — Stage 1
authors no negative policy — and the wording is corrected here rather than left as a fossil,
because a test file describing an architecture the code abandoned is read as a to-do.

Every bug this project has found lived where one of those arrows quietly changed meaning,
so each test names the arrow it is holding still.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import Config, WorkbookSchema
from apex_ads.models.identity import AdGroupKey
from apex_ads.util.queryid import QueryIdKey
from apex_ads.util.searchterm import SearchTerm
from apex_ads.watchdog import observations, taxonomy
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

    here = AdGroupKey(campaign="TST | Search | Brand | Jaipur", ad_group="Brand | Core")
    approved = coverage_for(
        term("anything at all", query_key), "apex hospital", "Exact", here, keywords
    )
    assert approved.status is CoverageStatus.APPROVED_HERE
    assert approved.covered

    unknown_keyword = coverage_for(
        term("anything at all", query_key), "keyword nobody approved", "Phrase", here, keywords
    )
    assert unknown_keyword.status is CoverageStatus.NOT_IN_WORKBOOK
    assert not unknown_keyword.covered

    # And when the export names nothing, the answer is UNKNOWN — never "not covered".
    silent = coverage_for(term("anything at all", query_key), "", "", here, keywords)
    assert silent.status is CoverageStatus.UNKNOWN
    assert not silent.covered


def test_an_approved_keyword_running_in_the_wrong_ad_group_is_not_green(
    bundle, query_key: QueryIdKey
) -> None:
    """Checking only the text called live drift APPROVED.

    The workbook places `apex hospital` in Brand | Core. If the account is running it in a
    different ad group, the export says so — campaign, ad group and keyword are all there —
    and the identity this project spent three phases establishing is exactly what compares
    them.
    """
    keywords = positives(bundle)
    elsewhere = AdGroupKey(campaign="TST | Search | Neuro | Jaipur", ad_group="Neuro | Provider")
    drifted = coverage_for(
        term("anything at all", query_key), "apex hospital", "Exact", elsewhere, keywords
    )
    assert drifted.status is CoverageStatus.APPROVED_ELSEWHERE
    # The demand is still covered — the placement is the separate problem.
    assert drifted.covered


def test_there_is_no_offline_positive_matcher_to_misuse() -> None:
    """The method that caused this is gone by name, not merely unused.

    `matched_by` was documented as "Google's semantics" and used for positive coverage.
    It is now `matched_by_negative`, which is what it always was.
    """
    from apex_ads.util.searchterm import SearchTerm as Term

    assert not hasattr(Term, "matched_by")
    assert hasattr(Term, "matched_by_negative")


def test_an_explicit_keyword_gap_is_not_held_demand(bundle, query_key: QueryIdKey) -> None:
    """ "The workbook has no keyword of its own for this query" — a fact, not a match."""
    keywords = positives(bundle)
    here = AdGroupKey(campaign="TST | Search | Brand | Jaipur", ad_group="Brand | Core")
    known = coverage_for(term("apex hospital", query_key), "apex hospital", "Exact", here, keywords)
    assert known.has_own_keyword

    novel = coverage_for(
        term("paralysis treatment cost jaipur", query_key), "apex hospital", "Exact", here, keywords
    )
    assert not novel.has_own_keyword
    # ...and that is NOT held demand: an approved keyword served it.
    assert novel.covered


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
    # The finding names the LIST, never the negative's text — a negative can be exactly
    # the query, and this detail reaches the handle-only actions report.
    assert "ACCOUNT_JUNK" in flagged[0].detail
    assert "junk vocabulary" in flagged[0].detail


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
                update={"explicit_keyword_gap_min_conversions": 1}
            )
        }
    )
    config = watchdog_config.model_copy(
        update={"rules": rules.model_copy(update={"watchdog": watchdog})}
    )
    export = read_export(exports["clean"], config.rules.watchdog, query_key)
    _, found = analyse(export, bundle, config)
    graded = [f for f in found if f.type is FindingType.EXPLICIT_KEYWORD_GAP]
    assert graded
    assert all(f.verdict == FLAGGED for f in graded)


# -------------------------------------------------------------- observations


def _observations(exports, bundle, config, key):
    export = read_export(exports["clean"], config.rules.watchdog, key)
    analysed, _ = analyse(export, bundle, config)
    return observations.build(
        analysed, taxonomy.build(bundle, config.rules), positives(bundle), config.rules
    )


def test_the_watchdog_proposes_no_negative_at_all(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The decision, asserted rather than described.

    Stage 1's Watchdog does not author negative policy. There is no `Candidate`, no
    `SUGGESTION`, and no module named `suggestions`.
    """
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("apex_ads.watchdog.suggestions")

    for item in _observations(exports, bundle, watchdog_config, query_key):
        assert item.kind in {
            observations.INTENTIONAL_NON_REACH,
            observations.OBSERVED_DESPITE_NEGATIVE,
        }


def test_an_intentional_exclusion_is_information_not_an_action(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """`ROUTE_COMPETITORS` excludes Brand deliberately, so the list behaved as approved.

    Two defects met here. The first proposed *extending* the list into Brand — rewriting a
    frozen decision. The fix stopped proposing, but still raised a weekly AMBER action,
    which asks Gaurav every Friday whether a decision he already made still stands. An
    incident becomes an action when it CONTRADICTS the decision; policy behaving as
    approved is information.
    """
    from apex_ads.models.config import SharedList

    approved = ["TST | Search | Neuro | Jaipur"]
    negatives_rules = watchdog_config.rules.negatives.model_copy(
        update={
            "shared_lists": {
                **watchdog_config.rules.negatives.shared_lists,
                "ROUTE_COMPETITORS": SharedList(applies_to=approved),
            }
        }
    )
    rules = watchdog_config.rules.model_copy(update={"negatives": negatives_rules})
    config = watchdog_config.model_copy(update={"rules": rules})

    competitor = bundle.negatives[0].model_copy(
        update={"text": "apex hospital", "match_type": "PHRASE", "list_name": "ROUTE_COMPETITORS"}
    )
    with_competitor = bundle.model_copy(update={"negatives": [*bundle.negatives, competitor]})

    export = read_export(exports["clean"], config.rules.watchdog, query_key)
    analysed, _ = analyse(export, with_competitor, config)
    seen = observations.build(
        analysed, taxonomy.build(with_competitor, config.rules), positives(with_competitor), rules
    )
    by_design = [item for item in seen if item.kind == observations.INTENTIONAL_NON_REACH]
    assert by_design, [item.kind for item in seen]

    for item in by_design:
        # the reach printed is the approved one, with Brand still absent
        assert item.approved_reach == tuple(approved)
        assert "Brand" not in " ".join(item.approved_reach)
        assert item.incident_campaign not in item.approved_reach
        assert item.remedy.startswith("None."), item.remedy

    # ...and it must not become a task.
    from apex_ads.watchdog import writeback

    rows = writeback.action_rows([], by_design, run_id="r")
    assert not rows, rows


def test_an_observation_is_never_worded_as_a_proposal(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """Vocabulary drift is how "observe" turns back into "suggest".

    The forbidden strings are phrases that read as the tool having acted or recommending
    an action — not every use of a word. "Applied" on its own is Google's term for
    attaching a shared list to a campaign, and the remedy legitimately asks whether the
    list *is applied*; banning the bare word would be a test that punishes correct English.
    """
    for item in _observations(exports, bundle, watchdog_config, query_key):
        text = f"{item.kind} {item.remedy}".casefold()
        for forbidden in (
            "we suggest",
            "suggested",
            "we propose",
            "proposed",
            "has been applied",
            "add this",
            "extend the list",
            "paste this",
        ):
            assert forbidden not in text, (forbidden, item)


def test_an_observed_negative_does_not_claim_the_account_is_misconfigured(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """ "The negative is not live in the account" was stronger than the evidence.

    No live account state, no change history. The term may have served before the negative
    was added. The remedy names the checks instead of asserting a cause.
    """
    despite = [
        item
        for item in _observations(exports, bundle, watchdog_config, query_key)
        if item.kind == observations.OBSERVED_DESPITE_NEGATIVE
    ]
    assert despite
    for item in despite:
        assert "not live" not in item.remedy
        assert "date range" in item.remedy
        assert "Phase 7" in item.remedy


def test_every_observation_names_an_already_approved_negative(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    approved = {negative.text for negative in bundle.negatives if negative.text}
    for item in _observations(exports, bundle, watchdog_config, query_key):
        assert item.negative_text in approved
        assert item.list_name


def test_every_observation_carries_its_evidence(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """A human must be able to judge it without re-running anything."""
    seen = _observations(exports, bundle, watchdog_config, query_key)
    assert seen
    for item in seen:
        assert item.query_ids
        assert item.remedy
        assert item.impressions >= 0


def test_statistical_junk_produces_no_observation(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """ "This got no clicks" is not evidence about which negative was involved."""
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    analysed, _ = analyse(export, bundle, watchdog_config)
    unresolved_junk = [
        item
        for item in analysed
        if item.classification.category is Category.UNRESOLVED
        and any(f.type is FindingType.JUNK for f in item.findings)
    ]
    assert unresolved_junk, "the fixture must contain impressions-no-clicks on an unknown term"

    seen = observations.build(
        analysed,
        taxonomy.build(bundle, watchdog_config.rules),
        positives(bundle),
        watchdog_config.rules,
    )
    ids = {qid for item in seen for qid in item.query_ids}
    for item in unresolved_junk:
        assert item.row.query_id not in ids


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


def test_held_demand_is_gone_because_the_dataset_cannot_support_it(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """A search-terms export contains only demand that **served**.

    Demand Google never served is, by construction, not in the file — so "this converted
    despite nothing covering it" is not a claim this dataset can make. Three implementations
    tried and each one was really reporting something else; the last fired on
    `NOT_IN_WORKBOOK` (drift) and `UNKNOWN` (ignorance) alike.
    """
    assert not hasattr(FindingType, "HELD_DEMAND")

    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    _, found = analyse(export, bundle, watchdog_config)
    assert not [f for f in found if f.type.value == "HELD_DEMAND"]


def test_an_unapproved_keyword_is_drift_and_not_a_coverage_gap(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The rows the old HELD_DEMAND fired on. They are drift, and say so."""
    export = read_export(exports["clean"], watchdog_config.rules.watchdog, query_key)
    analysed, _found = analyse(export, bundle, watchdog_config)
    drifted = [
        item
        for item in analysed
        if item.routing.coverage.status is CoverageStatus.NOT_IN_WORKBOOK
        and item.row.conversions > 0
    ]
    assert drifted, "the fixture must contain a converting unapproved keyword"
    for item in drifted:
        kinds = {f.type for f in item.findings}
        assert FindingType.UNAPPROVED_KEYWORD in kinds
        assert FindingType.EXPLICIT_KEYWORD_GAP not in kinds
        # These rows SERVED. Nothing about them may be reported as demand we did not
        # capture — that was the substitution, and it is what this row used to say.
        assert not {kind.value for kind in kinds} & {"HELD_DEMAND"}


def test_a_declared_seven_day_window_is_not_warned_about_for_a_quiet_last_day(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The declared range is the window; the Day column is when rows happened to be active.

    The fixture declares 2026-08-11 to 2026-08-17 and its rows stop on the 16th. Preferring
    observed dates warned about a correctly selected export as "6 day(s)" purely because
    nothing served on the last day.
    """
    from datetime import date

    export = read_export(
        exports["clean"], watchdog_config.rules.watchdog, query_key, today=date(2026, 8, 18)
    )
    assert export.declared_range == (date(2026, 8, 11), date(2026, 8, 17))
    assert export.activity_range == (date(2026, 8, 11), date(2026, 8, 16))
    assert not [f for f in export.findings if f.rule_id == "WD-003"]


def test_rows_outside_the_declared_window_are_reported(
    exports: dict[str, Path], watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The reverse failure: a wide selected window with activity in only part of it, and
    rows that fall outside the window entirely. Disagreement is reported, not reconciled."""
    from datetime import date

    from apex_ads.watchdog.ingest import Export, _range_findings

    export = Export(path=exports["clean"])
    export.declared_range = (date(2026, 8, 11), date(2026, 8, 17))
    export.activity_range = (date(2026, 8, 9), date(2026, 8, 19))
    findings = _range_findings(export, watchdog_config.rules.watchdog, today=date(2026, 8, 18))
    messages = " ".join(f.message for f in findings)
    assert "disagree with the selected range" in messages
    assert "before the selected" in messages
    assert "after the selected" in messages


def _competitor_scenario(
    exports: dict[str, Path],
    bundle,
    watchdog_config: Config,
    query_key: QueryIdKey,
    approved: list[str],
):
    """A competitor negative on `ROUTE_COMPETITORS`, approved against `approved` only."""
    from apex_ads.models.config import SharedList

    negatives_rules = watchdog_config.rules.negatives.model_copy(
        update={
            "shared_lists": {
                **watchdog_config.rules.negatives.shared_lists,
                "ROUTE_COMPETITORS": SharedList(applies_to=approved),
            }
        }
    )
    rules = watchdog_config.rules.model_copy(update={"negatives": negatives_rules})
    config = watchdog_config.model_copy(update={"rules": rules})

    competitor = bundle.negatives[0].model_copy(
        update={"text": "apex hospital", "match_type": "PHRASE", "list_name": "ROUTE_COMPETITORS"}
    )
    with_competitor = bundle.model_copy(update={"negatives": [*bundle.negatives, competitor]})

    export = read_export(exports["clean"], config.rules.watchdog, query_key)
    analysed, _ = analyse(export, with_competitor, config)
    seen = observations.build(
        analysed, taxonomy.build(with_competitor, config.rules), positives(with_competitor), rules
    )
    return analysed, seen


def test_an_intentional_exclusion_is_not_also_reported_as_a_leak(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The same event was simultaneously approved behaviour and a defect.

    `ROUTE_COMPETITORS` deliberately excludes Brand. The negative-policy section said
    "nothing to do — approved policy excludes this campaign" while the findings section, on
    the identical row, said competitor vocabulary had leaked. A reader cannot reconcile
    those, and the one that looks like a defect is the one they act on.
    """
    brand = "TST | Search | Brand | Jaipur"
    analysed, seen = _competitor_scenario(
        exports, bundle, watchdog_config, query_key, ["TST | Search | Neuro | Jaipur"]
    )

    in_brand = [
        item
        for item in analysed
        if item.classification.category is Category.COMPETITOR and item.row.campaign == brand
    ]
    assert in_brand, "the fixture must serve competitor vocabulary in Brand"
    for item in in_brand:
        assert FindingType.BRAND_LEAK not in {finding.type for finding in item.findings}

    by_design = [
        item
        for item in seen
        if item.kind == observations.INTENTIONAL_NON_REACH and item.incident_campaign == brand
    ]
    assert by_design, [(item.kind, item.incident_campaign) for item in seen]


def test_an_exclusion_that_does_reach_the_campaign_is_still_a_leak(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """The other direction, which the fix must not quietly disable.

    When the approved list *does* cover the campaign and the term served there anyway, that
    contradicts the decision. Both the finding and the action-bearing observation stand.
    """
    brand = "TST | Search | Brand | Jaipur"
    analysed, seen = _competitor_scenario(
        exports,
        bundle,
        watchdog_config,
        query_key,
        ["TST | Search | Neuro | Jaipur", brand],
    )

    in_brand = [
        item
        for item in analysed
        if item.classification.category is Category.COMPETITOR and item.row.campaign == brand
    ]
    assert in_brand
    for item in in_brand:
        assert FindingType.BRAND_LEAK in {finding.type for finding in item.findings}

    despite = [
        item
        for item in seen
        if item.kind == observations.OBSERVED_DESPITE_NEGATIVE and item.incident_campaign == brand
    ]
    assert despite
    assert not [item for item in seen if item.kind == observations.INTENTIONAL_NON_REACH]


def test_the_observation_does_not_depend_on_the_finding_it_explains(
    exports: dict[str, Path], bundle, watchdog_config: Config, query_key: QueryIdKey
) -> None:
    """`observations.build()` keyed off `FindingType.BRAND_LEAK` existing.

    That made the explanation a consequence of the thing it explains: the moment BRAND_LEAK
    correctly stopped firing for an intentionally-excluded campaign, the observation saying
    *why* it was excluded would have vanished with it — silently, in exactly the case a
    reader most needs it.
    """
    brand = "TST | Search | Brand | Jaipur"
    analysed, seen = _competitor_scenario(
        exports, bundle, watchdog_config, query_key, ["TST | Search | Neuro | Jaipur"]
    )
    kinds = {finding.type for item in analysed for finding in item.findings}
    assert not [
        item
        for item in analysed
        if item.row.campaign == brand
        and FindingType.BRAND_LEAK in {finding.type for finding in item.findings}
    ]
    assert FindingType.BRAND_LEAK in kinds, "still fires elsewhere; this is not a blanket removal"
    assert [item for item in seen if item.incident_campaign == brand]
