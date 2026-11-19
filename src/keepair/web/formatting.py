"""Display formatting. This is the only layer that turns stored values into text."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime

from keepair.money import micro_to_decimal


def format_money(amount_micro: int, currency: str) -> str:
    """One currency format everywhere (UX-14): 1,250.00 USD."""
    return f"{micro_to_decimal(amount_micro):,.2f} {currency}"


def format_unit_price(amount_micro: int, currency: str) -> str:
    """Small per-unit prices keep up to six decimals: 0.003 USD, 0.00025 USD."""
    text = f"{micro_to_decimal(amount_micro):,.6f}".rstrip("0")
    whole, _, frac = text.partition(".")
    return f"{whole}.{frac.ljust(2, '0')} {currency}"


def format_pct_bp(basis_points: int) -> str:
    """Hundredths of a percent to text: 8725 -> 87.25%."""
    return f"{basis_points // 100}.{basis_points % 100:02d}%"


def format_ts(value: datetime | None) -> str:
    """One date format everywhere (UX-14): 2026-01-15 09:00:00 UTC."""
    if value is None:
        return "never"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def period_end(period: str, start: date) -> date:
    months = {"MONTH": 1, "QUARTER": 3, "YEAR": 12}[period]
    last = start.month + months - 1
    year, month = start.year + (last - 1) // 12, (last - 1) % 12 + 1
    return date(year, month, calendar.monthrange(year, month)[1])


def format_period(period: str, start: date) -> str:
    return f"{period.capitalize()}, {start.isoformat()} to {period_end(period, start).isoformat()}"
