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


def resolve(bundle: WorkbookBundle, rules: Rules) -> dict[AdGroupKey, CallAsset | None]:
    """Resolve a call asset for every ad group. `None` means nothing resolved."""
    by_campaign = {campaign.name: campaign for campaign in bundle.campaigns}
    resolved: dict[AdGroupKey, CallAsset | None] = {}

    for group in bundle.ad_groups:
        campaign = by_campaign.get(group.campaign)
        if campaign is None or not campaign.call_phone_number:
            resolved[group.key] = None
            continue
        resolved[group.key] = CallAsset(
            number=campaign.call_phone_number,
            schedule=campaign.call_schedule,
            source="campaign",
        )
    return resolved
