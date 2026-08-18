"""The registry of every validator that runs.

Adding a rule means adding it here. Rule IDs are stable forever — retire one, never
renumber it — so this list is also the index a human uses to look one up.
"""

from __future__ import annotations

from apex_ads.ingest.urlcheck import UrlResult
from apex_ads.validate import (
    actions,
    ads,
    budget,
    crosscheck,
    keywords,
    landing_pages,
    negatives,
    settings,
    structure,
    tracking,
)
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
    # Ads and call assets — spec §9.6
    ads.HeadlineCount(),
    ads.HeadlineLength(),
    ads.DescriptionCount(),
    ads.DescriptionLength(),
    ads.EveryAdGroupHasAnAd(),
    ads.CallAssetResolves(),
    ads.NoDuplicateAssets(),
    ads.AssetTextIsClean(),
    ads.AdPaths(),
    ads.UniqueAssetNames(),
    ads.SupportingAssetsApproved(),
    ads.CallAssetIsReal(),
    # Landing pages — spec §9.6 (LP-003/004 are added by validators_for)
    landing_pages.LandingPageUrlIsValid(),
    landing_pages.OneLandingPagePerAdGroup(),
    # Tracking — spec §9.7
    tracking.PrimaryConversionDeclared(),
    tracking.CampaignGoalsExist(),
    tracking.AutoTaggingOn(),
    tracking.GclidPreserved(),
    tracking.RecommendedUtms(),
    tracking.TrackingTemplateSyntax(),
    tracking.SensitiveConversionsLocked(),
    # Settings hygiene — spec §9.8
    settings.SearchPartnersOff(),
    settings.DisplayExpansionOff(),
    settings.TargetsDeclared(),
    settings.LocationOptionDeclared(),
    # Action items — spec §9.9
    actions.NoOpenRedActions(),
    actions.OpenAmberActions(),
    actions.WaiversAreAccountable(),
    # The workbook's own panels
    crosscheck.PanelsAgreeWithTheRows(),
)


def validators_for(url_results: dict[str, UrlResult] | None = None) -> tuple[Validator, ...]:
    """Every validator, with the two that need URL results constructed around them.

    Passing `None` is not the same as omitting the check: `LP-003` then reports that
    reachability was not verified. A check that did not run must never read as one that
    passed.
    """
    return (
        *VALIDATORS,
        landing_pages.LandingPageReachable(url_results),
        landing_pages.LandingPageDomainAllowed(url_results),
    )


def rule_ids() -> tuple[str, ...]:
    return tuple(validator.rule_id for validator in validators_for())
