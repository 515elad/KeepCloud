"""Deterministic demo data (hard rule 2).

Fixed seed and fixed clock: running this twice leaves identical data.
Run with:  python -m keepair.demo.seed
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Connection, Engine, insert, text

from keepair.clock import Clock, FixedClock, to_iso
from keepair.config import Settings
from keepair.db import make_engine
from keepair.money import MICRO_PER_UNIT, Money
from keepair.rng import DEMO_SEED, seeded_rng
from keepair.schema import app_meta, demo_placeholder

DEMO_CLOCK_AT = datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC)
_TABLES = ("heartbeats", "alerts", "app_meta", "demo_placeholder")


def demo_clock() -> FixedClock:
    return FixedClock(DEMO_CLOCK_AT)


def seed(conn: Connection, clock: Clock, seed_value: int = DEMO_SEED) -> None:
    rng = seeded_rng(seed_value)
    conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY"))
    conn.execute(
        insert(app_meta),
        [
            {"key": "demo", "value": "true"},
            {"key": "demo_seed", "value": str(seed_value)},
            {"key": "demo_clock", "value": to_iso(clock.now())},
        ],
    )
    # Whole currency units between 500 and 5,000, in steps of 50.
    placeholder = Money(rng.randrange(500, 5001, 50) * MICRO_PER_UNIT, "USD")
    conn.execute(
        insert(demo_placeholder).values(
            id=1,
            label="Placeholder amount",
            amount_micro=placeholder.amount_micro,
            currency=placeholder.currency,
        )
    )
    # No heartbeats are seeded in phase 0: every component must show Unknown.


def run(engine: Engine) -> None:
    with engine.begin() as conn:
        seed(conn, demo_clock())


if __name__ == "__main__":
    run(make_engine(Settings()))
    print(f"Demo data loaded (seed {DEMO_SEED}, clock {to_iso(DEMO_CLOCK_AT)}).")
