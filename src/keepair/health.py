"""Component health from heartbeats (FR-21, SEC-37, UX-6).

A component is Unknown until its first heartbeat exists. Unknown is a state of
its own: it is never reported, coloured or counted as healthy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from keepair.clock import Clock
from keepair.schema import heartbeats


class HealthStatus(StrEnum):
    HEALTHY = "Healthy"
    DEGRADED = "Degraded"
    FAILING = "Failing"
    UNKNOWN = "Unknown"


@dataclass(frozen=True, slots=True)
class Component:
    id: str
    name: str
    degraded_after_s: int
    failing_after_s: int
    live_in_phase: int


# UX-6 health strip items, in display order.
COMPONENTS: tuple[Component, ...] = (
    Component("gateway", "Gateway", 60, 180, 2),
    Component("policy_sync", "Policy sync", 30, 60, 2),
    Component("ledger", "Ledger", 60, 180, 2),
    Component("egress", "Egress", 60, 180, 99),
    Component("alerting", "Alerting", 60, 180, 2),
    Component("data_sources", "Data sources", 86_400, 172_800, 4),
)
COMPONENT_IDS = frozenset(c.id for c in COMPONENTS)


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    component: Component
    status: HealthStatus
    last_heartbeat_at: datetime | None


def health_status(
    last_heartbeat_at: datetime | None,
    now: datetime,
    degraded_after_s: int,
    failing_after_s: int,
) -> HealthStatus:
    """status = Unknown when there is no heartbeat, otherwise by heartbeat age.

    age_s = now - last_heartbeat_at
    Healthy when age_s <= degraded_after_s; Degraded when age_s <= failing_after_s;
    Failing otherwise. A heartbeat dated in the future cannot be trusted: Unknown.
    """
    if last_heartbeat_at is None:
        return HealthStatus.UNKNOWN
    age_s = (now - last_heartbeat_at).total_seconds()
    if age_s < 0:
        return HealthStatus.UNKNOWN
    if age_s <= degraded_after_s:
        return HealthStatus.HEALTHY
    if age_s <= failing_after_s:
        return HealthStatus.DEGRADED
    return HealthStatus.FAILING


def unknown_health() -> list[ComponentHealth]:
    """What we may claim when the heartbeat store cannot be read: nothing."""
    return [ComponentHealth(c, HealthStatus.UNKNOWN, None) for c in COMPONENTS]


def read_health(conn: Connection, clock: Clock) -> list[ComponentHealth]:
    rows = conn.execute(select(heartbeats.c.component, heartbeats.c.last_heartbeat_at))
    last = {row.component: row.last_heartbeat_at for row in rows}
    now = clock.now()
    return [
        ComponentHealth(
            component=c,
            status=health_status(last.get(c.id), now, c.degraded_after_s, c.failing_after_s),
            last_heartbeat_at=last.get(c.id),
        )
        for c in COMPONENTS
    ]


def record_heartbeat(conn: Connection, component_id: str, clock: Clock) -> None:
    if component_id not in COMPONENT_IDS:
        raise ValueError(f"unknown component: {component_id}")
    stmt = insert(heartbeats).values(component=component_id, last_heartbeat_at=clock.now())
    stmt = stmt.on_conflict_do_update(
        index_elements=[heartbeats.c.component],
        set_={"last_heartbeat_at": stmt.excluded.last_heartbeat_at},
    )
    conn.execute(stmt)
