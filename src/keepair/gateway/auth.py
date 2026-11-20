"""Step 1: authenticate (FR-05).

The principal comes from the gateway credential and nothing else. Client
headers such as X-Team or X-Project are never read for attribution (B-07).
Revocation and expiry are checked in the database on every request, so a
revoked token stops working at once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, func, select

from keepair.gateway.errors import GatewayError
from keepair.gateway.tokens import hash_token, is_well_formed
from keepair.schema import agents, budgets, gateway_credentials, org_units, projects


@dataclass(frozen=True, slots=True)
class Principal:
    credential_id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    agent: str
    project_id: uuid.UUID
    project: str
    team: str
    budget_id: uuid.UUID | None


def authenticate(conn: Connection, authorization: str | None) -> Principal:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not is_well_formed(token.strip()):
        raise GatewayError("AUTHENTICATION_FAILED")
    c, a, p, t = gateway_credentials, agents, projects, org_units
    row = conn.execute(
        select(
            c.c.id, c.c.tenant_id, a.c.id.label("agent_id"), a.c.name.label("agent"),
            p.c.id.label("project_id"), p.c.name.label("project"), t.c.name.label("team"),
        )
        .select_from(
            c.join(a, a.c.id == c.c.agent_id)
            .join(p, p.c.id == a.c.project_id)
            .join(t, t.c.id == p.c.team_id)
        )
        .where(
            c.c.token_hash == hash_token(token.strip()),
            c.c.revoked_at.is_(None),
            c.c.expires_at > func.now(),
        )
    ).one_or_none()  # fmt: skip
    if row is None:
        raise GatewayError("AUTHENTICATION_FAILED")
    budget_id = conn.execute(
        select(budgets.c.id)
        .where(
            budgets.c.tenant_id == row.tenant_id,
            budgets.c.scope_type == "PROJECT",
            budgets.c.scope_id == row.project_id,
        )
        .order_by(budgets.c.period_start.desc())
        .limit(1)
    ).scalar_one_or_none()
    return Principal(
        row.id,
        row.tenant_id,
        row.agent_id,
        row.agent,
        row.project_id,
        row.project,
        row.team,
        budget_id,
    )
