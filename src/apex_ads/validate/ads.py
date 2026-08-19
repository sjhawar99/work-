"""Ad copy and call-asset rules (spec §9.6)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from apex_ads.models.config import Rules
from apex_ads.models.findings import Finding, Severity
from apex_ads.models.workbook import ResponsiveSearchAd, WorkbookBundle
from apex_ads.validate import callassets
from apex_ads.validate.base import Rule

SHEET = "02 BUILD"
EMOJI = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]", re.UNICODE)
UNSUPPORTED = re.compile(r"[{}<>\\^~`|]")
ALL_CAPS_WORD = re.compile(r"\b[A-Z]{2,}\b")


def _assets(ad: ResponsiveSearchAd, kind: str) -> list[tuple[str, str]]:
    source = ad.headlines if kind == "HEADLINE" else ad.descriptions
    return [(asset.column, asset.text) for asset in source]


class HeadlineCount(Rule):
    """`AD-001` — headline count within the configured range."""

    rule_id = "AD-001"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        limits = rules.ads.headlines
        for ad in bundle.ads:
            count = len(ad.headlines)
            if (limits.min is not None and count < limits.min) or (
                limits.max is not None and count > limits.max
            ):
                yield self.finding(
                    f"{ad.key} has {count} headlines; Google expects {limits.min} to {limits.max}",
                    sheet=ad.sheet,
                    row=ad.row,
                    section=ad.section,
                    entity=str(ad.key),
                    remedy="Add or remove headlines in the RSA 1 block.",
                )


class HeadlineLength(Rule):
    """`AD-002` — every headline within the character limit."""

    rule_id = "AD-002"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        limit = rules.ads.headlines.max_chars
        for ad in bundle.ads:
            for column, text in _assets(ad, "HEADLINE"):
                if len(text) > limit:
                    yield self.finding(
                        f"{ad.key} {column} is {len(text)} characters (limit {limit}): {text!r}",
                        sheet=ad.sheet,
                        row=ad.row,
                        section=ad.section,
                        column=column,
                        entity=str(ad.key),
                        remedy=f"Shorten it by {len(text) - limit} character(s).",
                    )


class DescriptionCount(Rule):
    """`AD-003` — description count within the configured range."""

    rule_id = "AD-003"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        limits = rules.ads.descriptions
        for ad in bundle.ads:
            count = len(ad.descriptions)
            if (limits.min is not None and count < limits.min) or (
                limits.max is not None and count > limits.max
            ):
                yield self.finding(
                    f"{ad.key} has {count} descriptions; "
                    f"Google expects {limits.min} to {limits.max}",
                    sheet=ad.sheet,
                    row=ad.row,
                    section=ad.section,
                    entity=str(ad.key),
                    remedy="Add or remove descriptions in the RSA 1 block.",
                )


class DescriptionLength(Rule):
    """`AD-004` — every description within the character limit."""

    rule_id = "AD-004"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        limit = rules.ads.descriptions.max_chars
        for ad in bundle.ads:
            for column, text in _assets(ad, "DESCRIPTION"):
                if len(text) > limit:
                    yield self.finding(
                        f"{ad.key} {column} is {len(text)} characters (limit {limit}): {text!r}",
                        sheet=ad.sheet,
                        row=ad.row,
                        section=ad.section,
                        column=column,
                        entity=str(ad.key),
                        remedy=f"Shorten it by {len(text) - limit} character(s).",
                    )


class EveryAdGroupHasAnAd(Rule):
    """`AD-005` — every ad group has an RSA with a destination."""

    rule_id = "AD-005"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        with_ads = {ad.key for ad in bundle.ads}
        for group in bundle.ad_groups:
            if group.key not in with_ads:
                yield self.finding(
                    f"{group.key} has no RSA",
                    sheet=group.sheet,
                    row=group.row,
                    section=group.section,
                    entity=str(group.key),
                    remedy="Add a row for it in the RSA 1 block.",
                )
            elif not group.planned_landing_page:
                yield self.finding(
                    f"{group.key} has no planned landing page",
                    sheet=group.sheet,
                    row=group.row,
                    section=group.section,
                    entity=str(group.key),
                    remedy="Fill the Planned landing page column.",
                )


class CallAssetResolves(Rule):
    """`AD-006` — every ad group resolves to exactly one call asset.

    Nine ad groups do not imply nine phone numbers (Decision A5). This requires nine
    *resolutions*, not nine entries: ad group → campaign → account, most specific wins.
    """

    rule_id = "AD-006"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        if not rules.ads.require_resolved_call_asset:
            return
        for key, asset in callassets.resolve(bundle, rules).items():
            if asset is None:
                yield self.finding(
                    f"{key} resolves to no call asset",
                    sheet=SHEET,
                    section="ad_groups",
                    entity=str(key),
                    remedy="Fill Call phone number on the campaign row in "
                    "CAMPAIGN SETTINGS, or add an override for this ad group.",
                )
            elif rules.ads.require_call_asset_schedule and not asset.schedule:
                # AD-008 in the spec was a second, weaker version of this check; it is
                # folded in here rather than shipped as a rule that reads a config key
                # nobody set.
                yield self.finding(
                    f"{key} has a call number but no staffed schedule",
                    sheet=SHEET,
                    section="ad_groups",
                    entity=str(key),
                    remedy="Fill Call schedule / reporting on the campaign row.",
                )


class NoDuplicateAssets(Rule):
    """`AD-007` — no repeated headline or description inside one ad."""

    rule_id = "AD-007"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        for ad in bundle.ads:
            for kind, texts in (
                ("headline", ad.headline_texts),
                ("description", ad.description_texts),
            ):
                for text, count in Counter(texts).items():
                    if count > 1:
                        yield self.finding(
                            f"{ad.key} repeats the {kind} {text!r} {count} times",
                            sheet=ad.sheet,
                            row=ad.row,
                            section=ad.section,
                            entity=str(ad.key),
                            remedy="Replace the duplicate; Google counts it once anyway.",
                        )


class AssetTextIsClean(Rule):
    """`AD-009` — no emoji, double spaces, unsupported characters or stray shouting."""

    rule_id = "AD-009"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        allowed_caps = {token.casefold() for token in rules.ads.allowed_all_caps_tokens}
        for ad in bundle.ads:
            for column, text in _assets(ad, "HEADLINE") + _assets(ad, "DESCRIPTION"):
                problems: list[str] = []
                if rules.ads.forbid_emoji and EMOJI.search(text):
                    problems.append("emoji")
                if rules.ads.forbid_double_spaces and "  " in text:
                    problems.append("double space")
                if UNSUPPORTED.search(text):
                    problems.append("unsupported characters")
                shouting = [
                    word
                    for word in ALL_CAPS_WORD.findall(text)
                    if word.casefold() not in allowed_caps
                ]
                if shouting:
                    problems.append(f"ALL-CAPS {shouting}")
                if problems:
                    yield self.finding(
                        f"{ad.key} {column}: {', '.join(problems)} in {text!r}",
                        sheet=ad.sheet,
                        row=ad.row,
                        section=ad.section,
                        column=column,
                        entity=str(ad.key),
                        remedy="Google disapproves ads for these; rewrite the asset.",
                    )


class AdPaths(Rule):
    """`AD-010` — display paths within the character limit.

    The workbook declares no path columns, so this reports itself as not applicable. A
    check that did not apply is never silently counted as a pass.
    """

    rule_id = "AD-010"
    severity = Severity.INFO

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        yield self.finding(
            "not applicable: the RSA block declares no display paths",
            sheet=SHEET,
            section="rsa",
            severity=Severity.INFO,
        )


class UniqueAssetNames(Rule):
    """`AD-011` — no duplicate text across supporting assets of the same type."""

    rule_id = "AD-011"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        counts = Counter(
            (asset.asset_type.casefold(), asset.text_header.casefold())
            for asset in bundle.supporting_assets
            if asset.text_header
        )
        for (asset_type, text), count in counts.items():
            if count > 1:
                yield self.finding(
                    f"{asset_type} {text!r} is declared {count} times",
                    sheet=SHEET,
                    section="supporting_assets",
                    entity=text,
                    remedy="Google rejects duplicate assets of the same type.",
                )


class SupportingAssetsApproved(Rule):
    """`AD-013` — every supporting asset carries an approving status.

    The model has always had a `status` field and nothing read it, while
    `MANUAL_STEPS.md` handed the asset to an operator without showing it. An asset marked
    `VERIFY FACT` — the real workbook has one — could be typed into the account as though
    it were approved.

    Ready-only, and BLOCKER at every status. The first version graded severity by whether
    the cell was *filled in*: blank blocked, `VERIFY FACT` merely warned. That got the
    danger backwards. A blank cell is an unfinished workbook; `VERIFY FACT` is a human
    saying "this claim about a hospital might not be true", and it was the one that
    reached a READY build. `ready_only` keeps development moving — `apex validate` reports
    it as a warning — while no deployable build can carry an unapproved asset.
    """

    rule_id = "AD-013"
    severity = Severity.BLOCKER
    ready_only = True

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        approved = {value.casefold() for value in rules.ads.approved_asset_statuses}
        for asset in bundle.supporting_assets:
            status = asset.status.strip()
            if status.casefold() not in approved:
                yield self.finding(
                    f"{asset.asset_type} {asset.text_header!r} has status "
                    f"{status or '(blank)'!r}, which is not one of "
                    f"{sorted(rules.ads.approved_asset_statuses)}",
                    sheet=asset.sheet,
                    row=asset.row,
                    section=asset.section,
                    entity=asset.text_header,
                    remedy="Approve the asset in SUPPORTING ASSETS, or remove it. An asset "
                    "nobody approved must not reach the account.",
                )


class CallAssetRegistryTargetsSomething(Rule):
    """`AD-014` — every call-asset registry row points at a level that exists.

    A registry row naming a campaign or ad group that is not in the workbook does nothing
    at all: resolution skips it and falls through to the campaign row, so the number a
    human deliberately entered is silently not the number the account gets. A typo in the
    ad-group name has to fail loudly, not quietly do nothing.
    """

    rule_id = "AD-014"
    severity = Severity.BLOCKER

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        campaigns = {campaign.name for campaign in bundle.campaigns}
        groups = {group.key for group in bundle.ad_groups}
        levels = set(rules.call_assets.resolution_order)

        for entry in bundle.call_asset_registry:
            problem: str | None = None
            if entry.level not in levels:
                problem = f"level {entry.level!r} is not one of {sorted(levels)}"
            elif entry.level == "CAMPAIGN" and entry.campaign not in campaigns:
                problem = f"names campaign {entry.campaign!r}, which is not in CAMPAIGN SETTINGS"
            elif entry.level == "AD_GROUP" and entry.key not in groups:
                problem = (
                    f"names ad group {entry.campaign!r} / {entry.ad_group!r}, which is not "
                    "in AD GROUP BUILD"
                )
            elif not entry.number:
                problem = "supplies no phone number, so it changes nothing"

            if problem is None:
                continue
            yield self.finding(
                f"CALL ASSET REGISTRY row {problem}",
                sheet=entry.sheet,
                row=entry.row,
                section=entry.section,
                entity=f"{entry.level} row {entry.row}",
                remedy="Correct the Level, Campaign and Ad group cells so the row targets "
                "something that exists, or delete the row. A row that targets nothing is "
                "not an override — it is an override that silently did not happen.",
            )


class CallAssetIsReal(Rule):
    """`AD-012` — the resolved call number and schedule are real values.

    Ready-only: `apex validate` reports it as a warning so development continues, and a
    deployable build cannot be produced until it is filled in.
    """

    rule_id = "AD-012"
    severity = Severity.BLOCKER
    ready_only = True

    def check(self, bundle: WorkbookBundle, rules: Rules) -> Iterable[Finding]:
        tokens = rules.call_assets.placeholder_tokens
        if not rules.call_assets.placeholder_blocks_ready_build:
            return
        reported: set[str] = set()
        for key, asset in callassets.resolve(bundle, rules).items():
            if asset is None or not asset.is_placeholder(tokens):
                continue
            if key.campaign in reported:
                continue
            reported.add(key.campaign)
            yield self.finding(
                f"{key.campaign} still has a placeholder call asset "
                f"(number {asset.number!r}, schedule {asset.schedule!r})",
                sheet=SHEET,
                section="campaigns",
                entity=key.campaign,
                remedy="Fill the real number and staffed hours in CAMPAIGN SETTINGS before launch.",
            )
