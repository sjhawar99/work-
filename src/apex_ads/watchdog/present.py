"""Derive truth once, render it everywhere.

Every fact in this module was, at some point, computed independently by the text report,
the HTML dashboard and the JSON manifest. Each time ingest learned something new, two of
the three kept describing the run the old way — and the prettiest artifact was reliably the
most confidently wrong one, because it is the one somebody screenshots.

Two facts live here:

* **What period did we analyse?** The declared window if the export printed one, the days
  that served otherwise, and `UNKNOWN` when neither is available. `Window.source` travels
  with the answer so the claim carries its own strength.
* **What did it cost?** A figure, plus the two separate reasons it may be less than the
  campaign's real spend. Rows that failed to parse are *our* incompleteness and a floor
  rather than a sum. Queries Google withholds for privacy are *its* incompleteness, present
  in every export, and no parser fixes them. The figure is therefore **reported search-term
  spend** — never "spend", which reads as the campaign's budget.

Rendering differs — a text column, an HTML card, a JSON field — but the *decision* is made
once, in this module, and the surfaces only choose a shape for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apex_ads.watchdog.ingest import Export

DECLARED = "declared"
ACTIVITY = "activity"
UNKNOWN = "unknown"

TOTAL_UNKNOWN = "TOTAL UNKNOWN"

SPEND_LABEL = "reported search-term spend"
"""The name of the figure, everywhere. Not "spend".

The word "spend" beside a number is read as the campaign's spend, and this number is
neither that nor a close approximation of it: it is the sum of the queries Google chose to
disclose. Naming it accurately is the whole fix — the arithmetic was never wrong, the label
was."""


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


@dataclass(frozen=True)
class Window:
    """The period this run describes, and how strongly we can claim it."""

    first: date | None
    last: date | None
    source: str

    @property
    def known(self) -> bool:
        return self.first is not None and self.last is not None

    @property
    def dates(self) -> str:
        return f"{self.first} to {self.last}" if self.known else "UNKNOWN"

    @property
    def qualifier(self) -> str:
        """Why this is the answer. Empty when there is nothing worth saying."""
        if self.source == DECLARED:
            return "the range selected in the export"
        if self.source == ACTIVITY:
            return "days with activity — the export printed no selected range"
        return "the export printed no date range and has no Day column, so the period is unverified"

    @property
    def line(self) -> str:
        """One line, for the report header and the dashboard subtitle alike."""
        if not self.known:
            return f"UNKNOWN — {self.qualifier}"
        return f"{self.dates} ({self.qualifier})"

    def as_dict(self) -> dict[str, str | None]:
        return {
            "first": str(self.first) if self.first else None,
            "last": str(self.last) if self.last else None,
            "source": self.source,
        }


def window(export: Export) -> Window:
    first, last = export.selected_range
    return Window(first=first, last=last, source=export.range_source)


def activity_window(export: Export) -> Window:
    """The days that actually served — kept beside `window()` for the manifest.

    Separate on purpose. Auditing a past run means being able to see both what period was
    selected and what period had traffic in it, without one having overwritten the other.
    """
    first, last = export.activity_range
    return Window(first=first, last=last, source=ACTIVITY if first and last else UNKNOWN)


@dataclass(frozen=True)
class Spend:
    """A money figure that knows what it is not.

    Two independent gaps, deliberately not merged. `parsed` is about rows we could not read
    — our problem, fixable. `undisclosed` is about queries Google never showed us — its
    policy, present in every export, and the reason the figure has the name it has.
    """

    figure: str
    parsed: bool
    unreadable: int
    undisclosed: str | None

    @property
    def line(self) -> str:
        """For the report's fixed-width header."""
        if self.parsed:
            return f"{self.figure}  ({SPEND_LABEL})"
        return (
            f"{self.figure} across readable rows — {TOTAL_UNKNOWN}, "
            f"{self.unreadable} row(s) could not be read ({SPEND_LABEL})"
        )

    @property
    def card_label(self) -> str:
        """For the dashboard card, whose label has to carry the caveat by itself."""
        return SPEND_LABEL if self.parsed else f"readable-row {SPEND_LABEL}"

    @property
    def card_note(self) -> str:
        parts = []
        if not self.parsed:
            parts.append(f"{TOTAL_UNKNOWN} · {self.unreadable} row(s) unreadable")
        if self.undisclosed is not None:
            parts.append(f"+ {self.undisclosed} on queries Google withheld")
        else:
            parts.append("excludes queries Google withholds")
        return " · ".join(parts)


def spend(export: Export) -> Spend:
    undisclosed = export.undisclosed_cost
    return Spend(
        figure=money(export.total_cost),
        parsed=export.spend_is_complete,
        unreadable=len(export.parse_errors),
        undisclosed=None if undisclosed is None else money(undisclosed),
    )
