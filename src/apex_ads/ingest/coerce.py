"""Reading one cell as one type, or failing loudly.

Coercion is explicit and total (spec §4.3 item 7). There is no path from a cell that
cannot be read to a `None` that quietly means zero — every failure names the sheet, the
row, the column and the offending value.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TypedDict

from apex_ads.ingest.errors import CellCoercionError
from apex_ads.ingest.grid import Row
from apex_ads.ingest.sections import Section
from apex_ads.util.currency import parse_currency
from apex_ads.util.text import CoercionError, is_null_token, normalise_text


class ProvenanceFields(TypedDict):
    """The provenance keyword arguments every record model needs."""

    sheet: str
    row: int
    section: str


class Reader:
    """Typed access to one row of one section, with provenance already attached."""

    def __init__(self, section: Section, row: Row) -> None:
        self.section = section
        self.row = row

    # ------------------------------------------------------------------ provenance
    @property
    def provenance(self) -> ProvenanceFields:
        return {
            "sheet": self.section.sheet,
            "row": self.row.number,
            "section": self.section.name,
        }

    # ---------------------------------------------------------------------- raw
    def raw(self, column: str) -> object:
        return self.row.value(self.section.columns.position(column))

    def is_null(self, column: str) -> bool:
        return is_null_token(self.raw(column))

    # --------------------------------------------------------------------- text
    def text(self, column: str, *, default: str = "") -> str:
        """Normalised text; a null token yields `default`. Case is never changed."""
        value = self.raw(column)
        return default if is_null_token(value) else normalise_text(str(value))

    def optional_text(self, column: str) -> str | None:
        value = self.raw(column)
        return None if is_null_token(value) else normalise_text(str(value))

    def text_list(self, column: str, separators: str = "·;,") -> list[str]:
        """Split a delimited cell such as `ACCOUNT_JUNK · OUTSIDE_GEO`, order preserved."""
        text = self.text(column)
        if not text:
            return []
        for separator in separators[1:]:
            text = text.replace(separator, separators[0])
        return [part.strip() for part in text.split(separators[0]) if part.strip()]

    # ------------------------------------------------------------------ numbers
    def decimal(self, column: str) -> Decimal:
        try:
            return parse_currency(self.raw(column))
        except CoercionError as exc:
            raise self._failure(column, exc.value, "a number") from exc

    def optional_decimal(self, column: str) -> Decimal | None:
        return None if self.is_null(column) else self.decimal(column)

    def optional_int(self, column: str) -> int | None:
        if self.is_null(column):
            return None
        value = self.decimal(column)
        if value != value.to_integral_value():
            raise self._failure(column, self.raw(column), "a whole number")
        return int(value)

    # --------------------------------------------------------------------- dates
    def optional_date(self, column: str) -> date | None:
        value = self.raw(column)
        if is_null_token(value):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        for pattern in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(normalise_text(str(value)), pattern).date()
            except ValueError:
                continue
        raise self._failure(column, value, "a date")

    # ------------------------------------------------------------------- errors
    def _failure(self, column: str, value: object, target: str) -> CellCoercionError:
        return CellCoercionError(
            sheet=self.section.sheet,
            section=self.section.name,
            row=self.row.number,
            column=column,
            value=value,
            target=target,
        )
