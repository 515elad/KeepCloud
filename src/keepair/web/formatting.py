"""Display formatting. This is the only layer that turns stored values into text."""

from __future__ import annotations

from datetime import UTC, datetime

from keepair.money import micro_to_decimal


def format_money(amount_micro: int, currency: str) -> str:
    """One currency format everywhere (UX-14): 1,250.00 USD."""
    return f"{micro_to_decimal(amount_micro):,.2f} {currency}"


def format_ts(value: datetime | None) -> str:
    """One date format everywhere (UX-14): 2026-01-15 09:00:00 UTC."""
    if value is None:
        return "never"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
