"""The demo's history of gateway usage: 1 to 14 January 2026.

One deterministic plan feeds two things, so that they reconcile:
- the seeded gateway usage records (estimates), and
- the generated provider billing files (keepair.demo.billing).

The plan spreads each project's seeded committed amount over days and models
with the largest-remainder method, so the parts add up to the budget exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from keepair.billing.allocation import split_amount
from keepair.demo.tree import demo_tree
from keepair.money import MICRO_PER_UNIT
from keepair.rng import DEMO_SEED, seeded_rng

FIRST_DAY = date(2026, 1, 1)
DAYS = 14
MODEL_3_LAST_DAY = date(2026, 1, 5)  # blocked on 6 January in the demo registry
USD_TO_EUR_MICROS = 920_000  # the demo's invented rate


@dataclass(frozen=True, slots=True)
class PlanRow:
    day: date
    project: str | None  # None: spend recorded on the team itself
    team: str
    model: str
    cost_micros: int  # in the budget's currency
    currency: str
    price_micros: int  # the same cost in the price list's currency (USD)


def to_price_micros(cost_micros: int, currency: str) -> int:
    if currency == "USD":
        return cost_micros
    return cost_micros * MICRO_PER_UNIT // USD_TO_EUR_MICROS


def usage_plan(seed_value: int = DEMO_SEED) -> list[PlanRow]:
    rng = seeded_rng(seed_value + 3)
    org, terms = demo_tree()
    rows: list[PlanRow] = []

    def walk(node, team: str, currency: str) -> None:
        currency = terms.get(node.name, (currency,))[0]
        if node.kind == "TEAM":
            team = node.name
        amount = node.committed * MICRO_PER_UNIT + node.extra_micros
        if node.kind in ("PROJECT", "TEAM") and amount:
            project = node.name if node.kind == "PROJECT" else None
            per_day = split_amount(amount, [rng.randrange(60, 140) for _ in range(DAYS)])
            for offset, day_amount in enumerate(per_day):
                day = FIRST_DAY + timedelta(days=offset)
                models = [("vendor-a/model-1", 60), ("vendor-a/model-2", 30)]
                if day <= MODEL_3_LAST_DAY:
                    models.append(("vendor-a/model-3", 10))
                parts = split_amount(day_amount, [w for _, w in models])
                for (model, _), cost in zip(models, parts, strict=True):
                    if cost:
                        rows.append(
                            PlanRow(day, project, team, model, cost, currency,
                                    to_price_micros(cost, currency))
                        )  # fmt: skip
        for child in node.children:
            walk(child, team, currency)

    walk(org, "", "USD")
    return rows
