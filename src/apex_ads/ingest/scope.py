"""Reading the `Scope` cell of `03 KEYWORDS`.

`Scope` is a human sentence, not an enum:

    Account
    Ad group
    Campaign: MLN | Search | Generic | Jaipur
    Shared list → Neuro, Generic, Ortho, Nephro

The raw text is preserved verbatim on every record and survives round-trip unchanged.
What this module produces is an *interpretation* of it — which is what Phase 3 will
cross-check against the approved `applies_to` in `rules.yaml` (`NEG-008`).
"""

from __future__ import annotations

import re

from apex_ads.ingest.errors import UnparsableScopeError
from apex_ads.models.config import ScopeParsing
from apex_ads.models.workbook import Scope
from apex_ads.util.text import normalise_text


class ScopeParser:
    """Compiled scope patterns from `workbook_schema.yaml`."""

    def __init__(self, spec: ScopeParsing) -> None:
        self.spec = spec
        self._account = re.compile(spec.account, re.IGNORECASE)
        self._ad_group = re.compile(spec.ad_group, re.IGNORECASE)
        self._campaign = re.compile(spec.campaign, re.IGNORECASE)
        self._shared_list = re.compile(spec.shared_list, re.IGNORECASE)

    def parse(
        self,
        raw: object,
        *,
        sheet: str,
        section: str,
        row: int,
        campaign: str | None,
        ad_group: str | None,
    ) -> Scope:
        """Interpret one scope cell. Raises `UnparsableScopeError` on anything unknown."""
        text = normalise_text(str(raw)) if raw is not None else ""

        if self._account.match(text):
            return Scope(raw=text, level="ACCOUNT")

        if self._ad_group.match(text):
            return Scope(raw=text, level="AD_GROUP", campaign=campaign, ad_group=ad_group)

        if match := self._campaign.match(text):
            return Scope(
                raw=text, level="CAMPAIGN", campaign=normalise_text(match.group("campaign"))
            )

        if match := self._shared_list.match(text):
            separator = self.spec.shared_list_campaign_separator
            names = [
                normalise_text(part)
                for part in match.group("campaigns").split(separator)
                if normalise_text(part)
            ]
            return Scope(raw=text, level="SHARED_LIST", applied_campaigns=names)

        raise UnparsableScopeError(sheet=sheet, section=section, row=row, value=text)
