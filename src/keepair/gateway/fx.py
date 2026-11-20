"""Currency conversion with versioned rates (PRD v1.4 Section 6, multi-currency).

A rate is stored as micro-units of the quote currency per one unit of the base
currency. Conversion rounds up, so a converted reservation is never too small.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, select

from keepair.money import MICRO_PER_UNIT
from keepair.schema import fx_rates


@dataclass(frozen=True, slots=True)
class Rate:
    base: str
    quote: str
    rate_micros: int
    effective_date: date | None


def convert(amount_micros: int, rate: Rate) -> int:
    return -(-amount_micros * rate.rate_micros // MICRO_PER_UNIT)


def lookup_rate(conn: Connection, base: str, quote: str, on: date) -> Rate | None:
    """The rate effective on the given date: the latest one not after it."""
    if base == quote:
        return Rate(base, quote, MICRO_PER_UNIT, None)
    row = conn.execute(
        select(fx_rates.c.rate_micros, fx_rates.c.effective_date)
        .where(fx_rates.c.base == base, fx_rates.c.quote == quote, fx_rates.c.effective_date <= on)
        .order_by(fx_rates.c.effective_date.desc())
        .limit(1)
    ).one_or_none()
    return Rate(base, quote, row.rate_micros, row.effective_date) if row else None
