"""Negative-keyword collision detection (spec §9.5).

This is the highest-value check in the system: a negative that blocks a keyword you are
paying for is invisible in the Google Ads interface and expensive in the account.

Two conditions must both hold for a collision:

1. **Scope overlap** — the negative must actually apply where the keyword lives.
2. **Match semantics** — Google's negative-match rules, on normalised tokens.

A negative is not dangerous because it *could* block some positive somewhere in the
account. It is dangerous when it blocks a positive **where that negative actually
applies**. A scope-blind check produces a wall of false blockers, and a wall of false
blockers teaches everyone to stop reading the report.
"""

from __future__ import annotations

from dataclasses import dataclass

from apex_ads.models.config import Rules
from apex_ads.models.workbook import Keyword, Negative, WorkbookBundle
from apex_ads.util.text import tokenise


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """True when `needle` appears as a contiguous run inside `haystack`."""
    if not needle or len(needle) > len(haystack):
        return False
    first = needle[0]
    for start in range(len(haystack) - len(needle) + 1):
        if haystack[start] == first and haystack[start : start + len(needle)] == needle:
            return True
    return False


def matches(negative_text: str, negative_match: str, keyword_text: str) -> bool:
    """Google's negative-match semantics on normalised tokens.

    Negatives do **not** match close variants — no plural, stemming or misspelling
    expansion. `job` does not block `jobs`, which is why the workbook lists both.
    """
    negative = tokenise(negative_text)
    keyword = tokenise(keyword_text)
    if not negative or not keyword:
        return False

    if negative_match == "BROAD":
        return set(negative).issubset(set(keyword))
    if negative_match == "PHRASE":
        return _is_subsequence(negative, keyword)
    if negative_match == "EXACT":
        return negative == keyword
    return False


@dataclass(frozen=True)
class ScopeResolver:
    """Answers "where does this negative actually apply?"

    Shared lists are the subtle case. The campaigns a list serves are declared in two
    places: approved policy in `rules.yaml`, and the workbook's own `Scope` cell.

    Collision checking uses **the workbook's Scope**, because that is the assignment that
    would actually be built. Policy is a cross-check, not an input — `NEG-008` reports any
    disagreement between the two, and between both and the operator routing in `02 BUILD`.

    Using the union of the two instead would be a mistake worth naming: whenever approved
    policy is broader than the workbook says, the engine would report collisions in
    campaigns the list does not reach. False blockers are not the safe direction — they
    train people to stop reading the report.
    """

    aliases: dict[str, list[str]]
    policy: dict[str, list[str]]

    @classmethod
    def from_rules(cls, rules: Rules) -> ScopeResolver:
        return cls(
            aliases=dict(rules.negatives.campaign_scope_aliases),
            policy={
                name: list(entry.applies_to) for name, entry in rules.negatives.shared_lists.items()
            },
        )

    def expand(self, short_names: list[str]) -> set[str]:
        """Short campaign names to exact campaign names, by the explicit alias map.

        Never substring matching: `"Neuro" in campaign_name` is a coincidence that holds
        only until a second Neuro campaign exists. An unmapped name expands to nothing
        and is reported by `NEG-009` rather than silently narrowing the scope.
        """
        expanded: set[str] = set()
        for short in short_names:
            expanded.update(self.aliases.get(short, []))
        return expanded

    def unmapped(self, short_names: list[str]) -> list[str]:
        return [short for short in short_names if short not in self.aliases]

    def campaigns_for_list(self, list_name: str | None, scope_names: list[str]) -> set[str]:
        """Campaigns a shared-list negative reaches, per the workbook's own Scope cell.

        Falls back to approved policy only when the Scope cell names nothing this tool can
        resolve — a fail-safe so an unreadable scope cannot silently switch collision
        checking off for that list. `NEG-009` reports the unresolved name separately.
        """
        from_scope = self.expand(scope_names)
        if from_scope:
            return from_scope
        return set(self.policy.get(list_name, [])) if list_name else set()

    def applies_to(self, negative: Negative, keyword: Keyword) -> bool:
        """Does this negative reach this keyword?

        The four branches below are exhaustive over `NegativeLevel`, and mypy verifies
        it — a fifth level could not be added without this failing to type-check.
        """
        scope = negative.scope
        if scope.level == "ACCOUNT":
            return True
        if scope.level == "SHARED_LIST":
            campaigns = self.campaigns_for_list(negative.list_name, scope.applied_campaigns)
            return keyword.campaign in campaigns
        if scope.level == "CAMPAIGN":
            return scope.campaign is not None and scope.campaign == keyword.campaign
        # AD_GROUP
        return negative.key is not None and negative.key == keyword.key


@dataclass(frozen=True)
class Collision:
    """One negative blocking one keyword, with everything a human needs to judge it."""

    negative: Negative
    keyword: Keyword

    def describe(self) -> str:
        scope = self.negative.scope
        where = scope.raw
        if scope.level == "SHARED_LIST" and self.negative.list_name:
            where = f"{self.negative.list_name} ({scope.raw})"
        return (
            f"negative {self.negative.text!r} ({self.negative.match_type.lower()}, {where}) "
            f"blocks the keyword {self.keyword.text!r} "
            f"({self.keyword.match_type.lower()}) in {self.keyword.key}"
        )


def find_collisions(bundle: WorkbookBundle, rules: Rules) -> list[Collision]:
    """Every negative that blocks a positive keyword within its own scope."""
    resolver = ScopeResolver.from_rules(rules)
    found: list[Collision] = []
    for negative in bundle.negatives:
        for keyword in bundle.keywords:
            if not resolver.applies_to(negative, keyword):
                continue
            if matches(negative.text, negative.match_type, keyword.text):
                found.append(Collision(negative=negative, keyword=keyword))
    return found
