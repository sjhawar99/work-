"""What this export proves about the demand it does *not* show — decided once.

Google can omit low-volume search terms from the search-terms report for privacy. That
single fact has been restated, independently, in five places: the report's standing note,
the dashboard's banner, the `WD-007` finding, the manifest, and the `Export` property behind
them. Each restatement drifted, and two of them drifted into saying things the data does not
support:

* the report told every reader *"those searches happened and cost money"* on runs whose own
  state said `NOT_PROVABLY_COMPLETE` — i.e. runs where nothing established that anything had
  been withheld at all;
* the finding asked *"was any metric on any aggregate row unreadable?"* rather than *"was
  the withheld-queries cost unreadable?"*, so a blank conversions cell on `Total: Search
  terms` produced *"this export states how much they cost but the figure could not be
  read"* on an export with no withheld-queries row in it.

So the question is answered here, once, in five named states, and every surface renders the
answer rather than re-deriving it. This module deliberately imports nothing from `ingest` or
`present` — it takes primitives — so both can depend on it without a cycle, and so neither
can be tempted to phrase the fact for itself.

**Absent evidence is not evidence of absence, in either direction.** No aggregate row does
not mean nothing was withheld; an unreadable cost does not mean zero. Both land in
`NOT_PROVABLY_COMPLETE`, and the wording says which one it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

NO_WITHHELD_AGGREGATE = "NO_WITHHELD_AGGREGATE"
WITHHELD_COST_KNOWN = "WITHHELD_COST_KNOWN"
WITHHELD_COST_ZERO = "WITHHELD_COST_ZERO"
WITHHELD_COST_UNREADABLE = "WITHHELD_COST_UNREADABLE"
WITHHELD_ACTIVITY_CONFIRMED_COST_UNKNOWN = "WITHHELD_ACTIVITY_CONFIRMED_COST_UNKNOWN"

NOT_PROVABLY_COMPLETE = "NOT_PROVABLY_COMPLETE"
WITHHELD_ACTIVITY_CONFIRMED = "WITHHELD_ACTIVITY_CONFIRMED"

DENOMINATOR = (
    "So every figure here is REPORTED SEARCH-TERM SPEND, and every percentage is a share of "
    "that — not of the campaign's budget. Check the campaign's own spend in Google Ads "
    "before acting on a share."
)
"""True in every state, which is why it is separate from the state-dependent sentence."""


@dataclass(frozen=True)
class Visibility:
    """One run's answer to "what does this file prove about what it is not showing?"."""

    state: str
    cost: Decimal | None
    """The withheld-queries spend when Google stated it readably. `None` is *not stated*."""

    has_activity: bool = False
    """Any positive metric on the withheld-queries row — impressions, clicks, cost, conv."""

    @property
    def epistemic(self) -> str:
        """`WITHHELD_ACTIVITY_CONFIRMED` only with positive evidence; otherwise unproven.

        Google's rules establish that low-volume queries *can* be omitted, not that any
        given week's export is missing something. Only Google's own aggregate, carrying
        traffic, turns "cannot be shown complete" into "we know something was withheld".

        Keyed on activity rather than on the state name, so a withheld row with zero cost
        but real impressions is still confirmed — the searches happened; they were free.
        """
        return WITHHELD_ACTIVITY_CONFIRMED if self.has_activity else NOT_PROVABLY_COMPLETE

    @property
    def confirmed(self) -> bool:
        return self.epistemic == WITHHELD_ACTIVITY_CONFIRMED

    @property
    def sentence(self) -> str:
        """What this export establishes, in one sentence. Never stronger than the state."""
        if self.state == WITHHELD_COST_KNOWN:
            assert self.cost is not None
            return (
                f"Google withheld low-volume search terms from this report and states they "
                f"cost {self.cost:,.2f}."
            )
        if self.state == WITHHELD_COST_ZERO:
            return (
                "Google states 0.00 of spend on the search terms it withheld from this "
                "report. That is what this file says about this window; it is not proof "
                "that nothing was withheld."
            )
        if self.state == WITHHELD_ACTIVITY_CONFIRMED_COST_UNKNOWN:
            return (
                "Google withheld search terms from this report — its own total shows "
                "traffic against them — but the cost figure could not be read, so the "
                "amount is UNKNOWN. Unknown, not zero."
            )
        if self.state == WITHHELD_COST_UNREADABLE:
            return (
                "This export carries Google's withheld-search-terms total and its cost "
                "could not be read, so the amount is UNKNOWN. Unknown, not zero."
            )
        return (
            "Google can omit low-volume search terms from this report for privacy. This "
            "export does not say whether it did, or what they cost — not stated, which is "
            "not zero. What is listed here cannot be shown to be everything."
        )

    @property
    def paragraph(self) -> str:
        return f"{self.sentence} {DENOMINATOR}"

    def as_dict(self) -> dict[str, str | None]:
        return {
            "state": self.state,
            "epistemic": self.epistemic,
            "withheld_cost": None if self.cost is None else str(self.cost),
        }


def assess(*, aggregate_present: bool, cost: Decimal | None, has_activity: bool) -> Visibility:
    """Decide the state from the **withheld-queries** aggregate alone.

    The arguments are deliberately narrow. The previous version asked "was any metric on any
    aggregate row unreadable?", which is a question about the whole footer block and answered
    a question about one row of it.
    """
    if not aggregate_present:
        return Visibility(state=NO_WITHHELD_AGGREGATE, cost=None, has_activity=False)
    if cost is None:
        state = (
            WITHHELD_ACTIVITY_CONFIRMED_COST_UNKNOWN if has_activity else WITHHELD_COST_UNREADABLE
        )
        return Visibility(state=state, cost=None, has_activity=has_activity)
    state = WITHHELD_COST_KNOWN if cost > 0 else WITHHELD_COST_ZERO
    return Visibility(state=state, cost=cost, has_activity=has_activity)
