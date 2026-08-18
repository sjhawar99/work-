"""The collision engine (spec §9.5) — the highest-value check in the system.

Two halves are tested separately, because they fail differently:

* `matches()` — Google's negative-match semantics on tokens.
* `ScopeResolver` — whether the negative reaches the keyword at all.

A scope-blind engine produces a wall of false blockers, which teaches everyone to stop
reading the report. A match-blind engine misses the real ones. Both are tested per match
type and per level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex_ads.ingest.workbook import parse_workbook
from apex_ads.models.config import Rules, WorkbookSchema
from apex_ads.models.workbook import Scope, WorkbookBundle
from apex_ads.validate.collisions import ScopeResolver, matches, scan
from apex_ads.validate.runner import run

# --------------------------------------------------------------------- semantics


@pytest.mark.parametrize(
    ("negative", "keyword", "expected"),
    [
        ("knee", "knee replacement jaipur", True),
        ("knee jaipur", "knee replacement jaipur", True),
        ("jaipur knee", "knee replacement jaipur", True),
        ("knee hip", "knee replacement jaipur", False),
        ("job", "hospital jobs jaipur", False),
    ],
)
def test_broad_negative_matches_every_token_in_any_order(
    negative: str, keyword: str, expected: bool
) -> None:
    assert matches(negative, "BROAD", keyword) is expected


@pytest.mark.parametrize(
    ("negative", "keyword", "expected"),
    [
        ("knee replacement", "best knee replacement jaipur", True),
        ("knee replacement", "knee replacement", True),
        ("replacement knee", "best knee replacement jaipur", False),
        ("knee jaipur", "knee replacement jaipur", False),
    ],
)
def test_phrase_negative_needs_a_contiguous_run(
    negative: str, keyword: str, expected: bool
) -> None:
    assert matches(negative, "PHRASE", keyword) is expected


@pytest.mark.parametrize(
    ("negative", "keyword", "expected"),
    [
        ("apex hospital", "apex hospital", True),
        ("apex hospital", "Apex  Hospital", True),
        ("apex hospital", "apex hospital jaipur", False),
    ],
)
def test_exact_negative_needs_the_whole_query(negative: str, keyword: str, expected: bool) -> None:
    assert matches(negative, "EXACT", keyword) is expected


def test_negatives_do_not_match_close_variants() -> None:
    """`job` does not block `jobs` — which is why the workbook lists both."""
    assert matches("job", "BROAD", "hospital jobs") is False
    assert matches("jobs", "BROAD", "hospital jobs") is True


def test_punctuation_and_case_are_normalised() -> None:
    assert matches("knee-replacement", "PHRASE", "Best Knee Replacement, Jaipur") is True


# -------------------------------------------------------------------------- scope


def test_short_names_resolve_only_through_the_alias_map(fixture_rules: Rules) -> None:
    """`"Neuro" in campaign_name` is a coincidence, not governance."""
    resolver = ScopeResolver.from_rules(fixture_rules)
    assert resolver.expand(["Neuro"]) == {"TST | Search | Neuro | Jaipur"}
    assert resolver.expand(["Cardio"]) == set()
    assert resolver.unmapped(["Neuro", "Cardio"]) == ["Cardio"]


# --------------------------------------------------------- collisions end to end


def collisions_in(path: Path, schema: WorkbookSchema, rules: Rules) -> list[str]:
    bundle = parse_workbook(path, schema)
    return [collision.describe() for collision in scan(bundle, rules).collisions]


def test_account_level_negative_collides_everywhere(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 4."""
    found = collisions_in(fixtures["collision_account"], schema, fixture_rules)
    assert found
    assert any("'apex'" in text and "apex hospital" in text for text in found)


def test_campaign_scoped_phrase_negative_collides_in_its_campaign(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 5."""
    found = collisions_in(fixtures["collision_campaign"], schema, fixture_rules)
    assert any("neurologist in jaipur" in text for text in found)


def test_the_same_negative_in_another_campaign_does_not_collide(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 6 — scope matters."""
    assert collisions_in(fixtures["collision_other_campaign"], schema, fixture_rules) == []


def test_shared_list_collides_where_the_list_is_applied(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 28."""
    found = collisions_in(fixtures["collision_shared_applied"], schema, fixture_rules)
    assert any("ROUTE_BRAND" in text and "neurologist in jaipur" in text for text in found)


def test_shared_list_does_not_collide_where_it_is_not_applied(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Acceptance test 29 — the case a union-of-sources resolver gets wrong."""
    assert collisions_in(fixtures["collision_shared_not_applied"], schema, fixture_rules) == []


def test_a_clean_workbook_has_no_collisions(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    assert collisions_in(fixtures["clean"], schema, fixture_rules) == []


def test_unresolvable_scope_is_unknown_not_zero(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """An unresolvable scope makes the answer UNKNOWN, never a quiet "no collisions".

    The engine must not borrow approved policy to fill the gap: its job is to describe
    what this workbook would build, not to repair an invalid one.
    """
    bundle = parse_workbook(fixtures["unknown_scope_alias"], schema)
    result = scan(bundle, fixture_rules)

    assert result.status == "UNKNOWN"
    assert [negative.text for negative in result.unevaluable] == ["cardiologist"]


def test_policy_is_never_substituted_for_an_unresolvable_scope(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Even when policy would have given the list a perfectly good reach."""
    negatives = fixture_rules.negatives.model_copy(
        update={
            "shared_lists": {
                name: entry.model_copy(update={"applies_to": ["TST | Search | Neuro | Jaipur"]})
                for name, entry in fixture_rules.negatives.shared_lists.items()
            }
        }
    )
    rules = fixture_rules.model_copy(update={"negatives": negatives})
    bundle = parse_workbook(fixtures["unknown_scope_alias"], schema)
    result = scan(bundle, rules)

    assert result.status == "UNKNOWN"
    assert not any("cardiologist" in c.describe() for c in result.collisions)


def test_unknown_collision_status_is_reported_as_a_blocker(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """A scan that could not check everything must not read as a clean scan."""
    bundle = parse_workbook(fixtures["unknown_scope_alias"], schema)
    result = run(bundle, fixture_rules)
    messages = [f.message for f in result.blockers if f.rule_id == "NEG-001"]
    assert any("collision status UNKNOWN" in message for message in messages), messages


def test_broader_approved_policy_does_not_invent_collisions(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """Policy may be broader than the workbook's Scope; that disagreement is NEG-008's
    to report, and must not manufacture collisions in campaigns the list never reaches."""
    negatives = fixture_rules.negatives.model_copy(
        update={
            "shared_lists": {
                name: entry.model_copy(update={"applies_to": ["TST | Search | Neuro | Jaipur"]})
                for name, entry in fixture_rules.negatives.shared_lists.items()
            }
        }
    )
    rules = fixture_rules.model_copy(update={"negatives": negatives})
    assert collisions_in(fixtures["collision_shared_not_applied"], schema, rules) == []


def test_collision_finding_names_both_sides_and_a_remedy(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    bundle = parse_workbook(fixtures["collision_account"], schema)
    result = run(bundle, fixture_rules)
    finding = next(f for f in result.blockers if f.rule_id == "NEG-001")
    assert "'apex'" in finding.message
    assert "blocks the keyword" in finding.message
    assert finding.row is not None
    assert "Narrow the negative" in finding.remedy


def test_unresolvable_scope_is_reported_not_silently_narrowed(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    """An unmapped short name must not quietly switch collision checking off."""
    bundle = parse_workbook(fixtures["unknown_scope_alias"], schema)
    result = run(bundle, fixture_rules)
    messages = [f.message for f in result.blockers if f.rule_id == "NEG-009"]
    assert any("Cardio" in message for message in messages), messages


def _inject(bundle: WorkbookBundle, **update: object) -> WorkbookBundle:
    negative = bundle.negatives[0].model_copy(update=update)
    return bundle.model_copy(update={"negatives": [negative]})


def test_ad_group_scope_reaches_only_its_own_ad_group(
    fixtures: dict[str, Path], schema: WorkbookSchema, fixture_rules: Rules
) -> None:
    bundle = parse_workbook(fixtures["clean"], schema)

    # Exact match, so it can only reach Brand | Core's "apex hospital" and not
    # Brand | Action's "apex hospital appointment".
    inside = _inject(
        bundle,
        text="apex hospital",
        match_type="EXACT",
        campaign="TST | Search | Brand | Jaipur",
        ad_group="Brand | Core",
        scope=Scope(
            raw="Ad group",
            level="AD_GROUP",
            campaign="TST | Search | Brand | Jaipur",
            ad_group="Brand | Core",
        ),
    )
    outside = _inject(
        bundle,
        text="apex hospital",
        match_type="EXACT",
        campaign="TST | Search | Brand | Jaipur",
        ad_group="Brand | Action",
        scope=Scope(
            raw="Ad group",
            level="AD_GROUP",
            campaign="TST | Search | Brand | Jaipur",
            ad_group="Brand | Action",
        ),
    )

    assert scan(inside, fixture_rules).collisions
    assert not scan(outside, fixture_rules).collisions
