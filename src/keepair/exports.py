"""CSV export with formula neutralization (SEC-29).

A spreadsheet program treats a cell that starts with ``=``, ``+``, ``-`` or
``@`` as a formula. Text that came from a person (a name, a reason, a tag) could
therefore run a formula on the reader's machine. Every text cell that starts
with one of those characters, also after leading white space, gets a leading
apostrophe, which makes the spreadsheet show it as text.

Amounts are written by this module from integers, as plain digits, and are
checked against a strict pattern. They are the only cells that are not treated
as text, so a negative amount stays a number.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from keepair.money import MICRO_PER_UNIT

# U+FF20 (full-width at sign) is treated as "@" by some spreadsheet programs.
FORMULA_STARTS = ("=", "+", "-", "@", "\uff20", "\t", "\r", "\n")
_NUMBER = re.compile(r"-?\d+\.\d{6}")


@dataclass(frozen=True, slots=True)
class Amount:
    """An exact amount in micro-units. Written with all six decimals, never rounded."""

    micros: int

    def text(self) -> str:
        sign = "-" if self.micros < 0 else ""
        whole, frac = divmod(abs(self.micros), MICRO_PER_UNIT)
        return f"{sign}{whole}.{frac:06d}"


def neutralize(value: str) -> str:
    """Make a text cell safe to open in a spreadsheet."""
    if value.lstrip(" ").startswith(FORMULA_STARTS) or value.startswith(FORMULA_STARTS):
        return "'" + value
    return value


def cell(value: str | Amount | None) -> str:
    if value is None:
        return ""
    if isinstance(value, Amount):
        text = value.text()
        if not _NUMBER.fullmatch(text):  # cannot happen for an integer; refuse rather than guess
            raise ValueError("amount is not a plain number")
        return text
    return neutralize(str(value))


def to_csv(header: list[str], rows: list[list[str | Amount | None]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow([neutralize(h) for h in header])
    for row in rows:
        writer.writerow([cell(v) for v in row])
    return out.getvalue()
