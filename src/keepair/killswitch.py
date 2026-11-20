"""Kill switch (FR-22, SEC-08, UX-7): stop all traffic, one vendor, or one project.

Switching on is one step. Switching off needs a second administrator and goes
through ``keepair.approvals``. The gateway reads the active switches with its
policy snapshot, which it reloads every 5 seconds, and refuses requests in
scope with KILL_SWITCH. The check comes before the budget, so it also holds
while the ledger is down.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Connection, func, insert, select, update

from keepair import audit
from keepair.clock import Clock
from keepair.ids import uuid7
from keepair.registry import clean_reason, subject_status
from keepair.rng import Rng
from keepair.schema import agents, gateway_decisions, kill_switches, projects

SCOPES = ("GLOBAL", "VENDOR", "PROJECT")
SCOPE_LABEL = {"GLOBAL": "All traffic", "VENDOR": "One vendor", "PROJECT": "One project"}
PREVIEW_WINDOW_S = 300
RECENT_WINDOW_S = 24 * 3600


class KillSwitchError(ValueError):
    """The message is safe to show."""


@dataclass(frozen=True, slots=True)
class Impact:
    scope_type: str
    scope_id: str
    scope_name: str
    projects: int
    agents: int
    requests_5m: int


def active_keys(conn: Connection, tenant_id: uuid.UUID) -> frozenset[tuple[str, str]]:
    """(scope type, scope id) of every switch that is on. Read by the gateway snapshot."""
    k = kill_switches
    rows = conn.execute(
        select(k.c.scope_type, k.c.scope_id).where(
            k.c.tenant_id == tenant_id, k.c.deactivated_at.is_(None)
        )
    )
    return frozenset((r.scope_type, r.scope_id) for r in rows)


def affects(keys: frozenset[tuple[str, str]], project_id: uuid.UUID, vendor_id: str | None) -> bool:
    """in_scope = global switch on, or the project's switch on, or the vendor's switch on."""
    return (
        ("GLOBAL", "") in keys
        or ("PROJECT", str(project_id)) in keys
        or (vendor_id is not None and ("VENDOR", vendor_id) in keys)
    )


def count_impact(decisions, scope_type: str, vendor_id: str, project_name: str, since_5m) -> tuple:
    """(projects, agents, requests in the last 5 minutes) among recent gateway decisions.

    A decision is in scope when the switch would have refused it: every decision for a
    global switch, the vendor's models for a vendor switch, the project's agents for a
    project switch.
    """

    def in_scope(d) -> bool:
        if scope_type == "GLOBAL":
            return True
        if scope_type == "VENDOR":
            return (d.model_id or "").split("/")[0] == vendor_id
        return d.project == project_name

    hit = [d for d in decisions if in_scope(d)]
    return (
        len({d.project for d in hit if d.project}),
        len({d.agent for d in hit if d.agent}),
        sum(1 for d in hit if d.occurred_at > since_5m),
    )


def preview(
    conn: Connection, tenant_id: uuid.UUID, scope_type: str, scope_id: str, now: datetime
) -> Impact:
    """What switching on would stop (UX-7 impact preview)."""
    name = _scope_name(conn, tenant_id, scope_type, scope_id)
    d = gateway_decisions
    recent = conn.execute(
        select(d.c.project, d.c.agent, d.c.model_id, d.c.occurred_at).where(
            d.c.tenant_id == tenant_id, d.c.occurred_at > now - timedelta(seconds=RECENT_WINDOW_S)
        )
    ).all()
    if scope_type == "GLOBAL":
        # Everything registered is affected, whether or not it sent traffic lately.
        n_projects = conn.execute(
            select(func.count()).select_from(projects).where(projects.c.tenant_id == tenant_id)
        ).scalar_one()
        n_agents = conn.execute(
            select(func.count()).select_from(agents).where(agents.c.tenant_id == tenant_id)
        ).scalar_one()
        _, _, requests = count_impact(
            recent, scope_type, "", "", now - timedelta(seconds=PREVIEW_WINDOW_S)
        )
    elif scope_type == "PROJECT":
        n_projects = 1
        n_agents = conn.execute(
            select(func.count())
            .select_from(agents)
            .where(agents.c.tenant_id == tenant_id, agents.c.project_id == uuid.UUID(scope_id))
        ).scalar_one()
        project_name = name.removeprefix("Project ")  # decisions carry the bare name
        _, _, requests = count_impact(
            recent, scope_type, "", project_name, now - timedelta(seconds=PREVIEW_WINDOW_S)
        )
    else:
        n_projects, n_agents, requests = count_impact(
            recent, scope_type, scope_id, "", now - timedelta(seconds=PREVIEW_WINDOW_S)
        )
    return Impact(scope_type, scope_id, name, n_projects, n_agents, requests)


def _scope_name(conn: Connection, tenant_id: uuid.UUID, scope_type: str, scope_id: str) -> str:
    if scope_type == "GLOBAL" and scope_id == "":
        return "All traffic"
    if scope_type == "VENDOR":
        if subject_status(conn, tenant_id, "vendor", scope_id) is not None:
            return f"Vendor {scope_id}"
    if scope_type == "PROJECT":
        try:
            project_id = uuid.UUID(scope_id)
        except ValueError:
            project_id = None
        found = conn.execute(
            select(projects.c.name).where(
                projects.c.tenant_id == tenant_id, projects.c.id == project_id
            )
        ).scalar_one_or_none()
        if found:
            return f"Project {found}"
    raise KillSwitchError("Choose all traffic, a registered vendor or an existing project.")


def activate(
    conn: Connection, clock: Clock, rng: Rng, *, tenant_id: uuid.UUID, scope_type: str,
    scope_id: str, actor, reason: str,
) -> uuid.UUID:  # fmt: skip
    """Switch on. One step (SEC-08). The caller has already checked step-up."""
    name = _scope_name(conn, tenant_id, scope_type, scope_id)
    reason = clean_reason(reason)
    k = kill_switches
    already = conn.execute(
        select(k.c.id).where(
            k.c.tenant_id == tenant_id, k.c.scope_type == scope_type, k.c.scope_id == scope_id,
            k.c.deactivated_at.is_(None),
        )
    ).first()  # fmt: skip
    if already is not None:
        raise KillSwitchError("This kill switch is already on.")
    switch_id = uuid7(clock, rng)
    conn.execute(
        insert(k).values(
            id=switch_id, tenant_id=tenant_id, scope_type=scope_type, scope_id=scope_id,
            scope_name=name, reason=reason, activated_by=actor.id,
            activated_by_name=actor.username, activated_at=clock.now(),
        )
    )  # fmt: skip
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor.username, actor_id=actor.id,
        action="kill_switch.activated", subject_type="kill_switch", subject_id=str(switch_id),
        after={"scope": scope_type, "scope_name": name, "on": True}, reason=reason,
    )  # fmt: skip
    return switch_id


def deactivate(
    conn: Connection, clock: Clock, *, tenant_id: uuid.UUID, switch_id: uuid.UUID, actor: str,
    actor_id: uuid.UUID | None, reason: str,
) -> None:  # fmt: skip
    """Switch off. Called only when a second administrator has approved."""
    k = kill_switches
    row = conn.execute(
        select(k).where(k.c.id == switch_id, k.c.tenant_id == tenant_id).with_for_update()
    ).one_or_none()
    if row is None or row.deactivated_at is not None:
        raise KillSwitchError("This kill switch is not on any more.")
    conn.execute(
        update(k)
        .where(k.c.id == switch_id)
        .values(deactivated_at=clock.now(), deactivated_by_name=actor)
    )
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor, actor_id=actor_id,
        action="kill_switch.deactivated", subject_type="kill_switch", subject_id=str(switch_id),
        before={"scope": row.scope_type, "scope_name": row.scope_name, "on": True},
        after={"on": False}, reason=reason,
    )  # fmt: skip
