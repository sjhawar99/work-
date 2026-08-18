"""The registry of every validator that runs.

Adding a rule means adding it here. Rule IDs are stable forever — retire one, never
renumber it — so this list is also the index a human uses to look one up.
"""

from __future__ import annotations

from apex_ads.validate import actions, budget, crosscheck, keywords, negatives, structure
from apex_ads.validate.base import Validator

VALIDATORS: tuple[Validator, ...] = (
    # Budget — spec §9.3
    budget.MonthlyBudgetTotal(),
    budget.PositiveBudgets(),
    budget.BudgetSplitDeclared(),
    budget.DailyBudgetDerivation(),
    budget.DeclaredTotalAgrees(),
    # Structure — spec §9.3, plus landing-page identity
    structure.CampaignCount(),
    structure.AdGroupCount(),
    structure.NoOrphans(),
    structure.CampaignNaming(),
    structure.NoDuplicateNames(),
    structure.CampaignNotEnabled(),
    structure.AdGroupHasKeywords(),
    structure.CampaignAliasesResolve(),
    structure.LandingPageIdentity(),
    # Keywords — spec §9.4
    keywords.NoBroadPositives(),
    keywords.OneAdGroupPerKeyword(),
    keywords.NoDuplicateKeywords(),
    keywords.KeywordTextIsUsable(),
    keywords.NearDuplicateKeywords(),
    keywords.AdGroupThemeDeclared(),
    keywords.KeywordLevelUrls(),
    keywords.LegacyMatchTypeNormalised(),
    keywords.DerivedCopyPasteValue(),
    # Negatives — spec §9.5, plus routing reconciliation
    negatives.NegativeCollisions(),
    negatives.NegativeScopeIsResolvable(),
    negatives.NoDuplicateNegatives(),
    negatives.RedundantNegatives(),
    negatives.DuplicateAcrossAppliedLists(),
    negatives.SharedListsAreApplied(),
    negatives.SharedListsAreDeclared(),
    negatives.RoutingSourcesAgree(),
    negatives.ScopeNamesResolve(),
    # Action items — spec §9.9
    actions.NoOpenRedActions(),
    actions.OpenAmberActions(),
    actions.WaiversAreAccountable(),
    # The workbook's own panels
    crosscheck.PanelsAgreeWithTheRows(),
)


def rule_ids() -> tuple[str, ...]:
    return tuple(validator.rule_id for validator in VALIDATORS)
