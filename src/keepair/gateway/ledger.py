"""Budget ledger: reserve, settle, release and expire (FR-05).

Every function runs inside the caller's transaction. Budget rows on the
reservation's path are locked with SELECT ... FOR UPDATE in ascending id
order, so two requests on the same path queue up and cannot deadlock.
The reservation row and the counter updates are written together.

Expiry times come from the database clock (SEC-35), never from the application.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, func, insert, select, text, update

from keepair import budgets as B
from keepair.clock import Clock
from keepair.gateway.errors import GatewayError
from keepair.ids import uuid7
from keepair.rng import Rng
from keepair.schema import budgets, reservations

OPEN_STATES = ("RESERVED", "HELD", "APPROVED")


@dataclass(frozen=True, slots=True)
class Limits:
    ttl_s: int = 240  # request timeout (120 s) + 120 s
    hold_ttl_s: int = 24 * 3600
    max_open: int = 100  # proposed in PRD v1.5 (reservation caps)
    max_held: int = 20


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True, slots=True)
class Reserved:
    reservation_id: uuid.UUID
    state: str
    path: tuple[uuid.UUID, ...]
    soft_limits_crossed: tuple[uuid.UUID, ...] = ()


def _budget_from_row(r) -> B.Budget:
    return B.Budget(
        id=r.id,
        parent_id=r.parent_id,
        scope_type=r.scope_type,
        scope_id=r.scope_id,
        cap_micros=r.cap_micros,
        currency=r.currency,
        period=r.period,
        period_start=r.period_start,
        mode=r.mode,
        policy=r.policy,
        committed_micros=r.committed_micros,
        reserved_micros=r.reserved_micros,
    )


def _lock_budgets(conn: Connection, ids: list[uuid.UUID]) -> dict[uuid.UUID, B.Budget]:
    rows = conn.execute(
        select(budgets).where(budgets.c.id.in_(ids)).order_by(budgets.c.id).with_for_update()
    )
    return {r.id: _budget_from_row(r) for r in rows}


def _apply(conn: Connection, ids, *, reserved_delta: int, committed_delta: int = 0) -> None:
    conn.execute(
        update(budgets)
        .where(budgets.c.id.in_(list(ids)))
        .values(
            reserved_micros=budgets.c.reserved_micros + reserved_delta,
            committed_micros=budgets.c.committed_micros + committed_delta,
            version=budgets.c.version + 1,
        )
    )


def budget_path_ids(
    conn: Connection, tenant_id: uuid.UUID, budget_id: uuid.UUID
) -> list[uuid.UUID]:
    """The limit path of a budget (keepair.budgets.constraint_path). Structure only, no locks."""
    all_budgets = B.load_budgets(conn, tenant_id)
    if budget_id not in all_budgets:
        raise GatewayError("NO_BUDGET")
    return [x.id for x in B.constraint_path(all_budgets[budget_id], all_budgets)]


def reserve(
    conn: Connection,
    *,
    clock: Clock,
    rng: Rng,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    budget_id: uuid.UUID,
    cost_micros: int,
    credential_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    model_id: str | None = None,
    price_version: int | None = None,
    fx_rate_micros: int | None = None,
    request_hash: bytes | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> Reserved:
    path_ids = budget_path_ids(conn, tenant_id, budget_id)
    locked = _lock_budgets(conn, path_ids)  # ascending id order
    own = locked[budget_id]
    hold = own.policy == "APPROVAL"

    if credential_id is not None:
        counts = dict(
            conn.execute(
                select(reservations.c.state, func.count())
                .where(
                    reservations.c.credential_id == credential_id,
                    reservations.c.state.in_(("RESERVED", "HELD")),
                )
                .group_by(reservations.c.state)
            ).all()
        )
        if counts.get("RESERVED", 0) >= limits.max_open or (
            hold and counts.get("HELD", 0) >= limits.max_held
        ):
            raise GatewayError("RATE_LIMITED", headers={"Retry-After": "30"})

    try:
        after = B.reserve(locked, budget_id, cost_micros)  # the one rule, shared with the UI
    except B.Denied as denied:
        raise GatewayError(denied.code, budget_id=denied.budget_id) from None

    crossed = tuple(
        x.id
        for x in locked.values()
        if x.policy == "SOFT"
        and x.committed_micros + x.reserved_micros
        <= x.cap_micros
        < after[x.id].committed_micros + after[x.id].reserved_micros
    )
    reservation_id = uuid7(clock, rng)
    state = "HELD" if hold else "RESERVED"
    ttl = limits.hold_ttl_s if hold else limits.ttl_s
    conn.execute(
        insert(reservations).values(
            id=reservation_id,
            tenant_id=tenant_id,
            request_id=request_id,
            credential_id=credential_id,
            agent_id=agent_id,
            budget_id=budget_id,
            budget_path=path_ids,
            state=state,
            model_id=model_id,
            reserved_micros=cost_micros,
            currency=own.currency,
            price_version=price_version,
            fx_rate_micros=fx_rate_micros,
            request_hash=request_hash if hold else None,
            # Database clock: now() + ttl (SEC-35).
            expires_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, ttl),
            created_at=clock.now(),
        )
    )
    _apply(conn, path_ids, reserved_delta=cost_micros)
    return Reserved(reservation_id, state, tuple(path_ids), crossed)


def find_hold(conn: Connection, agent_id: uuid.UUID, request_hash: bytes):
    """A live hold for the same agent and the same request: approved first, oldest first.

    The request body is never stored (D-07). A resubmission is recognized by the
    SHA-256 of its canonical form.
    """
    r = reservations
    return conn.execute(
        select(r.c.id, r.c.state, r.c.budget_path)
        .where(
            r.c.agent_id == agent_id,
            r.c.request_hash == request_hash,
            r.c.state.in_(("HELD", "APPROVED")),
            r.c.expires_at > func.now(),
        )
        .order_by(r.c.state, r.c.created_at)  # 'APPROVED' sorts before 'HELD'
        .limit(1)
        .with_for_update()
    ).one_or_none()


def activate_approved(
    conn: Connection, reservation_id: uuid.UUID, *, request_id: uuid.UUID, ttl_s: int
) -> bool:
    """Turn an approved hold into a live reservation for its one resubmission (UX-D2)."""
    result = conn.execute(
        update(reservations)
        .where(
            reservations.c.id == reservation_id,
            reservations.c.state == "APPROVED",
            reservations.c.expires_at > func.now(),
        )
        .values(
            state="RESERVED",
            request_id=request_id,
            expires_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, ttl_s),
        )
    )
    return result.rowcount == 1


def claim_for_dispatch(conn: Connection, reservation_id: uuid.UUID) -> bool:
    """Mark a live reservation as dispatched. False if there is none: then nothing may be sent."""
    result = conn.execute(
        update(reservations)
        .where(
            reservations.c.id == reservation_id,
            reservations.c.state == "RESERVED",
            reservations.c.dispatched_at.is_(None),
            reservations.c.expires_at > func.now(),
        )
        .values(dispatched_at=func.now())
    )
    return result.rowcount == 1


@dataclass(frozen=True, slots=True)
class Settled:
    reservation_id: uuid.UUID
    tenant_id: uuid.UUID
    budget_id: uuid.UUID
    reserved_micros: int
    actual_micros: int
    currency: str
    overrun_micros: int
    row: object = field(repr=False, default=None)


def _lock_reservation(conn: Connection, reservation_id: uuid.UUID, states: tuple[str, ...]):
    row = conn.execute(
        select(reservations).where(reservations.c.id == reservation_id).with_for_update()
    ).one_or_none()
    return row if row is not None and row.state in states else None


def settle(
    conn: Connection,
    reservation_id: uuid.UUID,
    *,
    clock: Clock,
    actual_micros: int | None,
    usage_known: bool = True,
    final_state: str = "SETTLED",
) -> Settled | None:
    """Settle once. Returns None when the reservation is not RESERVED any more.

    With actual_micros None the reservation settles at the reserved amount.
    """
    row = _lock_reservation(conn, reservation_id, ("RESERVED",))
    if row is None:
        return None
    actual = row.reserved_micros if actual_micros is None else actual_micros
    _lock_budgets(conn, list(row.budget_path))
    _apply(conn, row.budget_path, reserved_delta=-row.reserved_micros, committed_delta=actual)
    conn.execute(
        update(reservations)
        .where(reservations.c.id == reservation_id)
        .values(
            state=final_state,
            actual_micros=actual,
            usage_known=usage_known,
            settled_at=clock.now(),
        )
    )
    return Settled(
        reservation_id,
        row.tenant_id,
        row.budget_id,
        row.reserved_micros,
        actual,
        row.currency,
        max(0, actual - row.reserved_micros),
        row,
    )


def release(
    conn: Connection, reservation_id: uuid.UUID, *, clock: Clock, final_state: str = "RELEASED"
) -> bool:
    """Give back a reservation that will not be used. Nothing is committed."""
    row = _lock_reservation(conn, reservation_id, OPEN_STATES)
    if row is None:
        return False
    _lock_budgets(conn, list(row.budget_path))
    _apply(conn, row.budget_path, reserved_delta=-row.reserved_micros)
    conn.execute(
        update(reservations)
        .where(reservations.c.id == reservation_id)
        .values(state=final_state, actual_micros=0, settled_at=clock.now())
    )
    return True


@dataclass(frozen=True, slots=True)
class Expired:
    reservation_id: uuid.UUID
    was_state: str
    budget_id: uuid.UUID
    reserved_micros: int


def sweep_expired(conn: Connection, clock: Clock, batch: int = 200) -> list[Expired]:
    """Close reservations past their database-clock expiry.

    RESERVED: the request may have reached the provider, so it settles at the
    reserved amount with usage unknown. HELD or APPROVED: nothing was sent, so it is
    released. An approval that was not used within its window ends here.
    """
    rows = conn.execute(
        text(
            "SELECT id, state, budget_id, reserved_micros FROM reservations "
            "WHERE state IN ('RESERVED','HELD','APPROVED') AND expires_at < now() "
            "ORDER BY id LIMIT :batch FOR UPDATE SKIP LOCKED"
        ),
        {"batch": batch},
    ).all()
    done = []
    for row in rows:
        if row.state == "RESERVED":
            ok = settle(
                conn,
                row.id,
                clock=clock,
                actual_micros=None,
                usage_known=False,
                final_state="EXPIRED",
            )
        else:
            ok = release(conn, row.id, clock=clock, final_state="EXPIRED")
        if ok:
            done.append(Expired(row.id, row.state, row.budget_id, row.reserved_micros))
    return done
