"""Formula functions named by the help registry.

Each calculated field in ui/help/field_help.yaml names one entry here through
``formula_fn``. ``evaluate_on_demo`` runs the real function on the demo record
used in the registry's worked example and returns the inputs and the result as
the display strings the registry shows. A test compares the two, so the help
text cannot drift from the code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, select

from keepair.clock import Clock, to_iso
from keepair.health import COMPONENTS, health_status
from keepair.schema import demo_placeholder, heartbeats
from keepair.web.formatting import format_money


@dataclass(frozen=True, slots=True)
class Evaluated:
    inputs: dict[str, str]
    result: str


def _health_status_on_demo(conn: Connection, clock: Clock) -> Evaluated:
    component = COMPONENTS[0]
    last = conn.execute(
        select(heartbeats.c.last_heartbeat_at).where(heartbeats.c.component == component.id)
    ).scalar_one_or_none()
    now = clock.now()
    status = health_status(last, now, component.degraded_after_s, component.failing_after_s)
    return Evaluated(
        inputs={
            "component": component.id,
            "last_heartbeat_at": to_iso(last) if last else "none",
            "now": to_iso(now),
            "degraded_after_s": str(component.degraded_after_s),
            "failing_after_s": str(component.failing_after_s),
        },
        result=status.value,
    )


def _display_amount_on_demo(conn: Connection, clock: Clock) -> Evaluated:
    row = conn.execute(select(demo_placeholder).where(demo_placeholder.c.id == 1)).one()
    return Evaluated(
        inputs={"amount_micro": str(row.amount_micro), "currency": row.currency},
        result=format_money(row.amount_micro, row.currency),
    )


FORMULAS: dict[str, Callable[[Connection, Clock], Evaluated]] = {
    "health_status": _health_status_on_demo,
    "display_amount": _display_amount_on_demo,
}
