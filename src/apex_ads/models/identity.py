"""Canonical entity identity.

An ad group is identified by **`(Campaign, Ad group)`**, never by its name alone.

Today's nine ad-group names happen to be globally unique, so a name-only key works. That
is an accident of one hospital. The moment Apex adds Mansarovar, Bikaner or Udaipur:

    MLN | Search | Neuro | Jaipur          → Neuro | Provider
    Mansarovar | Search | Neuro | Jaipur   → Neuro | Provider

a landing-page brief that says `Neuro | Provider` identifies nothing. Convenient
uniqueness today must not become permanent schema tomorrow.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AdGroupKey(BaseModel):
    """The canonical composite key for an ad group."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign: str
    ad_group: str

    def __str__(self) -> str:
        return f"{self.campaign} / {self.ad_group}"
