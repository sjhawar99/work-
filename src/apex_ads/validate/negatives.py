"""Negative-keyword rules (spec §9.5), including the three-way routing reconciliation.

Routing is written down in three places, and each has a distinct job (Decision D6):

    rules.yaml → shared_lists.applies_to     approved routing policy
    03 KEYWORDS → Scope                      actual negative registry assignment
    02 BUILD → Negative lists / routing      operator build instruction

All three must agree, and none is silently preferred. They agree today; that is
reassuring once and dangerous forever, which is why it is checked rather than assumed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import WorkbookBundle
from apex_ads.validate.base import Rule
from apex_ads.validate.collisions import ScopeResolver, scan

SHEET = "03 KEYWORDS"


class NegativeCollisions(Rule):
    """`NEG-001` — no negative blocks a positive keyword within its own scope.

    The single highest-value check in the system: this defect class is invisible in the
    Google Ads interface and expensive in the account.
    """

    rule_id = "NEG-001"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if not rules.negatives.collision_check:
            return

        result = scan(bundle, rules)

        for negative in result.unevaluable:
            yield self.finding(
                f"collision status UNKNOWN for negative {negative.text!r}: its scope "
                f"{negative.scope.raw!r} names no campaign this tool can resolve, so it "
                "was not evaluated against any keyword",
                sheet=negative.sheet,
                row=negative.row,
                section=negative.section,
                entity=negative.list_name or negative.text,
                remedy="Fix the Scope cell, or add the campaign short name to "
                "negatives.campaign_scope_aliases (see NEG-009). Until then this "
                "negative is unchecked — not proven safe.",
            )

        for collision in result.collisions:
            negative, keyword = collision.negative, collision.keyword
            yield self.finding(
                collision.describe(),
                sheet=negative.sheet,
                row=negative.row,
                section=negative.section,
                entity=keyword.text,
                remedy=(
                    f"Narrow the negative, move it below {keyword.key}, remove that "
                    f"campaign from the list's scope, or stop buying the keyword "
                    f"(03 KEYWORDS row {keyword.row})."
                ),
            )


class NegativeScopeIsResolvable(Rule):
    """`NEG-002` — every negative names a level and an existing target."""

    rule_id = "NEG-002"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        campaigns = {campaign.name for campaign in bundle.campaigns}
        keys = {group.key for group in bundle.ad_groups}
        allowed = set(rules.negatives.allowed_levels)

        for negative in bundle.negatives:
            scope = negative.scope
            if scope.level not in allowed:
                yield self.finding(
                    f"negative {negative.text!r} has level {scope.level}, which is not "
                    f"one of {sorted(allowed)}",
                    sheet=negative.sheet,
                    row=negative.row,
                    section=negative.section,
                    entity=negative.text,
                    remedy="Correct the Scope cell.",
                )
            elif scope.level == "CAMPAIGN" and scope.campaign not in campaigns:
                yield self.finding(
                    f"negative {negative.text!r} is scoped to campaign "
                    f"{scope.campaign!r}, which does not exist",
                    sheet=negative.sheet,
                    row=negative.row,
                    section=negative.section,
                    entity=negative.text,
                    remedy="Correct the campaign name in Scope.",
                )
            elif scope.level == "AD_GROUP" and (negative.key is None or negative.key not in keys):
                target = str(negative.key) if negative.key else "(no campaign / ad group)"
                yield self.finding(
                    f"negative {negative.text!r} is scoped to ad group {target}, which "
                    "does not exist",
                    sheet=negative.sheet,
                    row=negative.row,
                    section=negative.section,
                    entity=negative.text,
                    remedy="Fill the Campaign and Ad group columns with a real ad group.",
                )


class NoDuplicateNegatives(Rule):
    """`NEG-003` — no exact duplicate negative at the same level and scope."""

    rule_id = "NEG-003"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        counts = Counter(
            (negative.scope.raw, negative.list_name, negative.text, negative.match_type)
            for negative in bundle.negatives
        )
        for (scope, list_name, text, match), count in counts.items():
            if count > 1:
                where = list_name or scope
                yield self.finding(
                    f"negative {text!r} ({match.lower()}) appears {count} times in {where}",
                    sheet=SHEET,
                    section="keyword_registry",
                    entity=text,
                    remedy="Remove the duplicate rows.",
                )


class RedundantNegatives(Rule):
    """`NEG-004` — a scoped negative already covered by an identical account-level one."""

    rule_id = "NEG-004"
    severity = Severity.WARNING

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        account = {
            (negative.text, negative.match_type)
            for negative in bundle.negatives
            if negative.scope.level == "ACCOUNT"
        }
        for negative in bundle.negatives:
            if negative.scope.level == "ACCOUNT":
                continue
            if (negative.text, negative.match_type) in account:
                yield self.finding(
                    f"negative {negative.text!r} is already blocked account-wide, so this "
                    f"{negative.scope.level.lower().replace('_', ' ')} copy does nothing",
                    sheet=negative.sheet,
                    row=negative.row,
                    section=negative.section,
                    entity=negative.text,
                    remedy="Remove the narrower copy to keep the registry readable.",
                )


class DuplicateAcrossAppliedLists(Rule):
    """`NEG-005` — the same negative in two lists that both serve one campaign."""

    rule_id = "NEG-005"
    severity = Severity.WARNING

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        resolver = ScopeResolver.from_rules(rules)
        reach: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

        for negative in bundle.negatives:
            if negative.scope.level != "SHARED_LIST" or not negative.list_name:
                continue
            campaigns = resolver.campaigns_for_list(negative.scope.applied_campaigns)
            for campaign in campaigns:
                reach[(negative.text, negative.match_type)][campaign].add(negative.list_name)

        for (text, match), by_campaign in reach.items():
            for campaign, lists in by_campaign.items():
                if len(lists) > 1:
                    yield self.finding(
                        f"negative {text!r} ({match.lower()}) reaches {campaign} through "
                        f"{len(lists)} lists ({', '.join(sorted(lists))})",
                        sheet=SHEET,
                        section="keyword_registry",
                        entity=text,
                        remedy="Keep it in one list so removing it later actually removes it.",
                    )


class SharedListsAreApplied(Rule):
    """`NEG-006` — a declared shared list serves at least one campaign.

    A list applied to nothing does nothing, and reads on the page as protection that is
    not there.
    """

    rule_id = "NEG-006"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        resolver = ScopeResolver.from_rules(rules)
        used = {
            negative.list_name
            for negative in bundle.negatives
            if negative.scope.level == "SHARED_LIST" and negative.list_name
        }
        for name, entry in rules.negatives.shared_lists.items():
            scope_campaigns: set[str] = set()
            for negative in bundle.negatives:
                if negative.list_name == name and negative.scope.level == "SHARED_LIST":
                    scope_campaigns |= resolver.expand(negative.scope.applied_campaigns)
            if not entry.applies_to and not scope_campaigns:
                yield self.finding(
                    f"shared list {name!r} is applied to no campaign"
                    + (" and has no members" if name not in used else ""),
                    sheet="config/rules.yaml",
                    section="negatives.shared_lists",
                    entity=name,
                    remedy="Give it an applies_to in config/rules.yaml, or remove the list.",
                )


class SharedListsAreDeclared(Rule):
    """`NEG-007` — a shared-list negative names a list declared in config."""

    rule_id = "NEG-007"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        declared = set(rules.negatives.shared_lists)
        for negative in bundle.negatives:
            if negative.scope.level != "SHARED_LIST":
                continue
            if not negative.list_name:
                yield self.finding(
                    f"negative {negative.text!r} is scoped to a shared list but names none",
                    sheet=negative.sheet,
                    row=negative.row,
                    section=negative.section,
                    entity=negative.text,
                    remedy="Fill the List name column.",
                )
            elif negative.list_name not in declared:
                yield self.finding(
                    f"negative {negative.text!r} names shared list "
                    f"{negative.list_name!r}, which is not declared in config",
                    sheet=negative.sheet,
                    row=negative.row,
                    section=negative.section,
                    entity=negative.list_name,
                    remedy="Add the list to negatives.shared_lists in config/rules.yaml, "
                    "or correct the List name cell.",
                )


class RoutingSourcesAgree(Rule):
    """`NEG-008` — the three routing encodings agree.

    Compared per shared list:

        policy    rules.yaml → shared_lists.applies_to
        registry  03 KEYWORDS → Scope, short names expanded via the alias map
        build     02 BUILD → Negative lists / routing, by the ad groups naming the list

    Account-level lists are excluded: they apply everywhere by definition, so a routing
    cell mentioning one is informational and cannot narrow its scope.
    """

    rule_id = "NEG-008"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        resolver = ScopeResolver.from_rules(rules)
        account_lists = set(rules.negatives.account_lists)

        registry: dict[str, set[str]] = defaultdict(set)
        for negative in bundle.negatives:
            if negative.scope.level == "SHARED_LIST" and negative.list_name:
                registry[negative.list_name] |= resolver.expand(negative.scope.applied_campaigns)

        build: dict[str, set[str]] = defaultdict(set)
        for group in bundle.ad_groups:
            for name in group.negative_lists:
                if name not in account_lists:
                    build[name].add(group.campaign)

        names = set(rules.negatives.shared_lists) | set(registry) | set(build)
        for name in sorted(names - account_lists):
            policy = (
                set(rules.negatives.shared_lists[name].applies_to)
                if (name in rules.negatives.shared_lists)
                else set()
            )
            sources = {
                "approved policy (rules.yaml)": policy,
                "registry Scope (03 KEYWORDS)": registry.get(name, set()),
                "operator routing (02 BUILD)": build.get(name, set()),
            }
            present = {label: value for label, value in sources.items() if value}
            if len(present) < 2 or len({frozenset(value) for value in present.values()}) == 1:
                continue

            detail = "; ".join(
                f"{label}: {sorted(value) or 'none'}" for label, value in sources.items()
            )
            yield self.finding(
                f"shared list {name!r} is routed differently by each source — {detail}",
                sheet="03 KEYWORDS",
                section="keyword_registry",
                entity=name,
                remedy="Make all three agree. None of them is authoritative on its own: "
                "config is what was approved, Scope is what was written, and "
                "02 BUILD is what the operator was told to do.",
            )


class ScopeNamesResolve(Rule):
    """`NEG-009` — every short campaign name in a Scope cell has an alias.

    An unmapped short name expands to nothing, which would silently narrow a negative's
    scope and quietly switch off collision checking for it. Resolution is by the explicit
    alias map — never substring matching.
    """

    rule_id = "NEG-009"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        resolver = ScopeResolver.from_rules(rules)
        for negative in bundle.negatives:
            if negative.scope.level != "SHARED_LIST":
                continue
            if unmapped := resolver.unmapped(negative.scope.applied_campaigns):
                yield self.finding(
                    f"scope {negative.scope.raw!r} names {unmapped}, which has no entry in "
                    "campaign_scope_aliases",
                    sheet=negative.sheet,
                    row=negative.row,
                    section=negative.section,
                    entity=negative.list_name or negative.text,
                    remedy="Add the short name to negatives.campaign_scope_aliases in "
                    "config/rules.yaml, mapping it to exact campaign names.",
                )
