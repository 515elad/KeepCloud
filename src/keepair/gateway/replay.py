"""Replay the fail-open spool into the ledger once it is reachable (SEC-06).

Each record becomes, in one transaction: a fail-open event, the spend on every
budget of its limit path, a usage record and a decision record. The record ID
is the event's primary key, so replaying a record twice changes nothing.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Engine, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from keepair.clock import Clock, to_iso
from keepair.gateway import ledger
from keepair.gateway.spool import Entry, Spool
from keepair.ids import uuid7
from keepair.rng import Rng
from keepair.schema import fail_events, gateway_decisions, usage_events


def _uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def replay_entry(conn, entry: Entry, clock: Clock, rng: Rng) -> bool:
    """Apply one record. Returns False when it had already been applied."""
    d = entry.data
    tenant_id, record_id = uuid.UUID(d["tenant_id"]), uuid.UUID(entry.id)
    if entry.kind == "denied":
        result = conn.execute(
            pg_insert(gateway_decisions)
            .values(
                id=record_id, tenant_id=tenant_id, occurred_at=entry.opened_at,
                agent_id=_uuid(d.get("agent_id")), agent=d.get("agent"), project=d.get("project"),
                requested_model=d.get("requested_model"), model_id=None, outcome="DENIED",
                reason_code=d["reason"], http_status=d["status"],
                budget_id=_uuid(d.get("budget_id")),
            )
            .on_conflict_do_nothing()
        )  # fmt: skip
        return result.rowcount == 1

    done = entry.done
    known = bool(done and done.get("usage_known"))
    amount = done["actual_micros"] if done else d["estimate_micros"]
    now = clock.now()
    inserted = conn.execute(
        pg_insert(fail_events)
        .values(
            id=record_id, tenant_id=tenant_id, occurred_at=entry.opened_at, kind="FAIL_OPEN",
            budget_id=_uuid(d["budget_id"]), agent=d["agent"], project=d["project"],
            model_id=d["model_id"], amount_micros=amount, currency=d["currency"],
            usage_known=known, replayed_at=now,
            detail={
                "estimate_micros": d["estimate_micros"],
                "answered": done is not None,
                "spooled_at": to_iso(entry.opened_at),
                "reconciled": True,
            },
        )
        .on_conflict_do_nothing()
        .returning(fail_events.c.id)
    ).one_or_none()  # fmt: skip
    if inserted is None:
        return False
    # The same cost in the price list's currency; the estimate when no answer was recorded.
    price_micros = (done or {}).get("price_micros", d.get("price_estimate_micros")) if amount else 0
    path = [uuid.UUID(x) for x in d["budget_path"]]
    ledger._lock_budgets(conn, path)
    ledger._apply(conn, path, reserved_delta=0, committed_delta=amount)
    conn.execute(
        insert(usage_events).values(
            id=uuid7(clock, rng), tenant_id=tenant_id, provider=d["vendor_id"],
            model_id=d["model_id"], agent_id=_uuid(d["agent_id"]), team=d["team"],
            project=d["project"], agent=d["agent"],
            input_tokens=done.get("input_tokens") if done else None,
            output_tokens=done.get("output_tokens") if done else None,
            actual_micros=amount, currency=d["currency"], usage_known=known,
            price_micros=price_micros,
            price_currency=d.get("price_currency"), source="GATEWAY",
            occurred_at=entry.opened_at, ingested_at=now,
        )
    )  # fmt: skip
    conn.execute(
        pg_insert(gateway_decisions)
        .values(
            id=record_id, tenant_id=tenant_id, occurred_at=entry.opened_at,
            agent_id=_uuid(d["agent_id"]), agent=d["agent"], project=d["project"],
            requested_model=d["requested_model"], model_id=d["model_id"], outcome="ALLOWED",
            reason_code="FAIL_OPEN", http_status=200, budget_id=_uuid(d["budget_id"]),
            snapshot_version=d.get("snapshot_version"),
        )
        .on_conflict_do_nothing()
    )  # fmt: skip
    return True


def replay(engine: Engine, spool: Spool, clock: Clock, rng: Rng) -> int:
    """Replay everything that is ready. Returns how many records were newly applied."""
    applied = 0
    for entry in spool.pending():
        with engine.begin() as conn:
            if replay_entry(conn, entry, clock, rng):
                applied += 1
        # Marked only after the commit. A crash in between replays it again, harmlessly.
        spool.mark_replayed(entry.id)
    spool.compact()
    return applied
