"""Resolving which call asset an ad group actually uses (Decision A5).

Stage 1 uses one default number across all five campaigns, with optional overrides.
Resolution is **most-specific-wins** — ad group, then campaign, then account — matching
how Google resolves call assets across levels.

The number itself is an approved account value and lives in the **workbook**
(`02 BUILD → CAMPAIGN SETTINGS`, columns `Call phone number` and
`Call schedule / reporting`). Config holds only the resolution order and the vocabulary
of placeholder tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

from apex_ads.models.config import Rules
from apex_ads.models.identity import AdGroupKey
from apex_ads.models.workbook import WorkbookBundle


@dataclass(frozen=True)
class CallAsset:
    """The call asset an ad group resolves to, and where it came from."""

    number: str
    schedule: str
    source: str
    """`campaign` or `account` — which level supplied the value."""

    def is_placeholder(self, tokens: list[str]) -> bool:
        """True while the workbook still says `[REQUIRED BEFORE LAUNCH]` or similar."""
        marks = [token.strip().casefold() for token in tokens]
        for value in (self.number, self.schedule):
            folded = value.strip().casefold()
            if not folded or any(folded.startswith(mark) for mark in marks if mark):
                return True
        return False


def _level_value(
    level: str, key: AdGroupKey, bundle: WorkbookBundle, rules: Rules
) -> CallAsset | None:
    """The call asset one level supplies for one ad group, or `None` if it supplies none."""
    overrides = rules.call_assets.overrides

    if level == "AD_GROUP":
        entry = overrides.ad_groups.get(str(key))
        if entry and entry.number:
            return CallAsset(
                number=entry.number, schedule=entry.schedule or "", source="ad group override"
            )
        return None

    if level == "CAMPAIGN":
        entry = overrides.campaigns.get(key.campaign)
        if entry and entry.number:
            return CallAsset(
                number=entry.number, schedule=entry.schedule or "", source="campaign override"
            )
        for campaign in bundle.campaigns:
            if campaign.name == key.campaign and campaign.call_phone_number:
                return CallAsset(
                    number=campaign.call_phone_number,
                    schedule=campaign.call_schedule,
                    source="campaign",
                )
        return None

    default = rules.call_assets.account_default
    if default.number:
        return CallAsset(
            number=default.number, schedule=default.schedule or "", source="account default"
        )
    return None


def resolve(bundle: WorkbookBundle, rules: Rules) -> dict[AdGroupKey, CallAsset | None]:
    """Resolve a call asset for every ad group, most specific level first.

    Decision A5: ad group, then campaign, then account. The order is read from
    `rules.call_assets.resolution_order` rather than hard-coded, so the config key is real
    rather than decorative — it was previously declared and never consulted, while the
    resolver only ever looked at the campaign row.
    """
    resolved: dict[AdGroupKey, CallAsset | None] = {}
    for group in bundle.ad_groups:
        found: CallAsset | None = None
        for level in rules.call_assets.resolution_order:
            found = _level_value(level, group.key, bundle, rules)
            if found is not None:
                break
        resolved[group.key] = found
    return resolved
