"""Resolving which call asset an ad group actually uses (Decision A5).

Stage 1 uses one default number across all five campaigns, with optional exceptions.
Resolution is **most-specific-wins** — ad group, then campaign, then account — matching
how Google resolves call assets across levels.

**Every number comes from the workbook.** Three levels can supply one:

* `AD_GROUP` — a `CALL ASSET REGISTRY` row naming a campaign and an ad group;
* `CAMPAIGN` — a registry row naming a campaign, else the `CAMPAIGN SETTINGS` row;
* `ACCOUNT` — a registry row with no campaign.

`rules.yaml` holds the order and the placeholder vocabulary, and nothing that could ever
be a phone number. Overrides used to live in config, which put an approved account value
in the rules file and produced two answers to one question — the validator checked the
config number while `MANUAL_STEPS.md` printed the campaign row's. There is one answer now,
and `resolve()` is the only thing that produces it: validators, `MANUAL_STEPS.md` and the
manifest all read the same `CallAsset`.
"""

from __future__ import annotations

from dataclasses import dataclass

from apex_ads.models.config import Rules
from apex_ads.models.identity import AdGroupKey
from apex_ads.models.workbook import CallAssetEntry, WorkbookBundle


@dataclass(frozen=True)
class CallAsset:
    """The call asset an ad group resolves to, and the exact row it came from."""

    number: str
    schedule: str
    source: str
    """Which kind of row supplied it — `ad group registry`, `campaign registry`,
    `campaign row` or `account registry`."""
    sheet: str
    row: int
    section: str
    """The actual cell provenance.

    `source` alone said "campaign registry" and left somebody to find which of nine rows
    that was. The first question anybody asks about a number in a live account is *why is
    this number here*, and the answer has to be a row, not a category.
    """

    @property
    def provenance(self) -> str:
        """`02 BUILD row 91 · ad group registry` — what a human needs to go and look."""
        return f"{self.sheet} row {self.row} · {self.source}"

    def is_placeholder(self, tokens: list[str]) -> bool:
        """True while the workbook still says `[REQUIRED BEFORE LAUNCH]` or similar."""
        marks = [token.strip().casefold() for token in tokens]
        for value in (self.number, self.schedule):
            folded = value.strip().casefold()
            if not folded or any(folded.startswith(mark) for mark in marks if mark):
                return True
        return False


def effective_scope(entry: CallAssetEntry) -> tuple[str, ...]:
    """What a registry row actually governs, as opposed to what it appears to say.

    The grammar (`AD-014`) exists because these two can come apart. A row reading
    `Level: ACCOUNT · Campaign: Neuro` looks specific to a person and applies account-wide
    to the machine; `Level: CAMPAIGN · Ad group: Neuro | Provider` looks like one ad group
    and covers the whole campaign. Both were legal. Neither is now.
    """
    if entry.level == "ACCOUNT":
        return ("ACCOUNT",)
    if entry.level == "CAMPAIGN":
        return ("CAMPAIGN", entry.campaign)
    if entry.level == "AD_GROUP":
        return ("AD_GROUP", entry.campaign, entry.ad_group)
    return (entry.level, entry.campaign, entry.ad_group)


def _entry_asset(entry: CallAssetEntry, source: str) -> CallAsset | None:
    if not entry.number:
        return None
    return CallAsset(
        number=entry.number,
        schedule=entry.schedule,
        source=source,
        sheet=entry.sheet,
        row=entry.row,
        section=entry.section,
    )


def _level_value(
    level: str, key: AdGroupKey, bundle: WorkbookBundle, rules: Rules
) -> CallAsset | None:
    """The call asset one level supplies for one ad group, or `None` if it supplies none."""
    registry = bundle.call_asset_registry

    if level == "AD_GROUP":
        for entry in registry:
            if entry.key == key:
                asset = _entry_asset(entry, "ad group registry")
                if asset is not None:
                    return asset
        return None

    if level == "CAMPAIGN":
        for entry in registry:
            if entry.level == "CAMPAIGN" and entry.campaign == key.campaign:
                asset = _entry_asset(entry, "campaign registry")
                if asset is not None:
                    return asset
        for campaign in bundle.campaigns:
            if campaign.name == key.campaign and campaign.call_phone_number:
                return CallAsset(
                    number=campaign.call_phone_number,
                    schedule=campaign.call_schedule,
                    source="campaign row",
                    sheet=campaign.sheet,
                    row=campaign.row,
                    section=campaign.section,
                )
        return None

    for entry in registry:
        if entry.level == "ACCOUNT":
            asset = _entry_asset(entry, "account registry")
            if asset is not None:
                return asset
    return None


def resolve(bundle: WorkbookBundle, rules: Rules) -> dict[AdGroupKey, CallAsset | None]:
    """Resolve a call asset for every ad group, most specific level first.

    Decision A5: ad group, then campaign, then account. The order is read from
    `rules.call_assets.resolution_order` rather than hard-coded, so the config key is real
    rather than decorative — it was previously declared and never read, while the resolver
    only ever looked at the campaign row.

    This is a pure function of `(bundle, rules)` and it is the **only** producer of a
    `CallAsset`. Nothing else may reach for `campaign.call_phone_number` directly: that is
    how the number validated and the number printed came apart.
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
