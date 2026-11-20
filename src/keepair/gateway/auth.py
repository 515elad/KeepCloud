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
    budget_currency: str | None = None
    budget_path: tuple[uuid.UUID, ...] = ()
    # True when every budget on the limit path is monitor or soft with fail mode FAIL_OPEN.
    fail_open_eligible: bool = False


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
    t_b = budgets
    rows = {
        r.id: r
        for r in conn.execute(
            select(
                t_b.c.id, t_b.c.parent_id, t_b.c.mode, t_b.c.policy, t_b.c.fail_mode,
                t_b.c.currency, t_b.c.scope_type, t_b.c.scope_id, t_b.c.period_start,
            ).where(t_b.c.tenant_id == row.tenant_id)
        )
    }  # fmt: skip
    own = max(
        (r for r in rows.values() if r.scope_type == "PROJECT" and r.scope_id == row.project_id),
        key=lambda r: r.period_start,
        default=None,
    )
    path: list = []
    current = own
    while current is not None and current.id not in {r.id for r in path}:
        path.append(current)
        current = rows.get(current.parent_id) if current.mode == "SUBDIVISION" else None
    eligible = bool(path) and all(
        r.policy in ("MONITOR", "SOFT") and r.fail_mode == "FAIL_OPEN" for r in path
    )
    return Principal(
        row.id, row.tenant_id, row.agent_id, row.agent, row.project_id, row.project, row.team,
        own.id if own else None,
        own.currency if own else None,
        tuple(r.id for r in path),
        eligible,
    )  # fmt: skip


CACHE_TTL_S = 30


class PrincipalCache:
    """Last successful lookups, used only while the database cannot be reached.

    When the database is up, every request is checked there, so revocation is
    immediate. During an outage a credential seen in the last 30 seconds is
    still accepted (SEC-12: revoked within 30 s); anything else is refused.
    """

    def __init__(self, clock) -> None:
        self._clock = clock
        self._entries: dict[bytes, tuple[Principal, object]] = {}

    @staticmethod
    def malformed(authorization: str | None) -> bool:
        scheme, _, token = (authorization or "").partition(" ")
        return scheme.lower() != "bearer" or not is_well_formed(token.strip())

    def put(self, token_hash: bytes, principal: Principal) -> None:
        self._entries[token_hash] = (principal, self._clock.now())

    def get(self, authorization: str | None) -> Principal | None:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not is_well_formed(token.strip()):
            return None
        entry = self._entries.get(hash_token(token.strip()))
        if entry is None or (self._clock.now() - entry[1]).total_seconds() > CACHE_TTL_S:
            return None
        return entry[0]


def token_hash_of(authorization: str | None) -> bytes | None:
    scheme, _, token = (authorization or "").partition(" ")
    return hash_token(token.strip()) if scheme.lower() == "bearer" else None
