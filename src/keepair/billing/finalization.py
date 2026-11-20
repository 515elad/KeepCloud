"""Finalization state of a money figure (FR-07, UX-8).

    ESTIMATED          what the gateway calculated from its own price list
    PROVIDER_REPORTED  what the provider's usage export says
    INVOICED           what an invoice says

An estimate is not a charge. Figures of different states are shown side by
side and are never added together: ``Figure.__add__`` refuses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Finalization(StrEnum):
    ESTIMATED = "ESTIMATED"
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    INVOICED = "INVOICED"


LABEL = {
    Finalization.ESTIMATED: "Estimated",
    Finalization.PROVIDER_REPORTED: "Provider-reported",
    Finalization.INVOICED: "Invoiced",
}


class MixedFigures(TypeError):
    """An attempt to add figures of different states or currencies."""


@dataclass(frozen=True, slots=True)
class Figure:
    amount_micros: int
    currency: str
    state: Finalization

    def __add__(self, other: Figure) -> Figure:
        if not isinstance(other, Figure):
            return NotImplemented
        if other.state is not self.state or other.currency != self.currency:
            raise MixedFigures(
                f"cannot add {self.state} {self.currency} and {other.state} {other.currency}"
            )
        return Figure(self.amount_micros + other.amount_micros, self.currency, self.state)


def gateway_figure(amount_micros: int, currency: str) -> Figure:
    """Anything the gateway computed is an estimate. There is no other way to build one."""
    return Figure(amount_micros, currency, Finalization.ESTIMATED)


@dataclass(frozen=True, slots=True)
class Source:
    """A billing source may supply exactly one finalization state."""

    id: str
    label: str
    provider: str
    state: Finalization


SOURCES: dict[str, Source] = {
    s.id: s
    for s in (
        Source(
            "vendor-a-usage", "vendor-a usage export", "vendor-a", Finalization.PROVIDER_REPORTED
        ),
        Source("vendor-a-invoice", "vendor-a invoice", "vendor-a", Finalization.INVOICED),
    )
}


def billing_figure(amount_micros: int, currency: str, state: str) -> Figure:
    final = Finalization(state)
    if final is Finalization.ESTIMATED:
        raise ValueError("a billing record is never an estimate")
    return Figure(amount_micros, currency, final)
