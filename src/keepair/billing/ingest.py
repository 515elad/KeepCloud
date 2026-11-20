"""Load a parsed billing file (FR-01). Idempotent by (source, record key, revision).

- The same record and revision again, unchanged: counted, nothing written.
- The same record and revision with other content: the whole file is quarantined.
  A correction must come as a higher revision.
- A higher revision: the new record becomes current; the earlier one is kept.

Everything for one file happens in one transaction. A quarantined file loads nothing.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, func, insert, select, update

from keepair.billing import allocation as A
from keepair.billing.finalization import SOURCES
from keepair.billing.focus import BillingRow, Quarantine, parse
from keepair.clock import Clock
from keepair.ids import uuid7
from keepair.rng import Rng
from keepair.schema import (
    allocation_facts,
    allocation_rules,
    ingestion_batches,
    manual_allocations,
    normalized_cost_records,
    org_units,
    projects,
    raw_billing_records,
)


@dataclass(slots=True)
class BatchResult:
    batch_id: uuid.UUID
    status: str
    rows_total: int = 0
    rows_new: int = 0
    rows_revised: int = 0
    rows_unchanged: int = 0
    reasons: list[str] = field(default_factory=list)


def payload_hash(row: BillingRow) -> bytes:
    canonical = json.dumps(row.payload(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def load_projects(conn: Connection, tenant_id: uuid.UUID) -> list[A.ProjectRef]:
    rows = conn.execute(
        select(projects.c.id, projects.c.name, org_units.c.name.label("team"))
        .select_from(projects.join(org_units, org_units.c.id == projects.c.team_id))
        .where(projects.c.tenant_id == tenant_id)
        .order_by(projects.c.name)
    )
    return [A.ProjectRef(r.id, r.name, r.team) for r in rows]


def load_rules(conn: Connection, tenant_id: uuid.UUID) -> list[A.Rule]:
    rows = conn.execute(select(allocation_rules).where(allocation_rules.c.tenant_id == tenant_id))
    return [
        A.Rule(
            id=r.id,
            name=r.name,
            priority=r.priority,
            effective_from=r.effective_from,
            effective_to=r.effective_to,
            match=dict(r.match),
            split=tuple((s["project"], int(s["weight_bp"])) for s in r.split),
            version=r.version,
        )
        for r in rows
    ]


def reallocate(
    conn: Connection, tenant_id: uuid.UUID, record_ids: list[uuid.UUID], clock: Clock
) -> None:
    """Recompute the allocation facts of the given current records. Earlier facts are kept."""
    if not record_ids:
        return
    n, f = normalized_cost_records, allocation_facts
    project_refs, rules = load_projects(conn, tenant_id), load_rules(conn, tenant_id)
    manual = {
        (r.source, r.record_key): r.project_id
        for r in conn.execute(
            select(manual_allocations).where(manual_allocations.c.tenant_id == tenant_id)
        )
    }
    conn.execute(
        update(f).where(f.c.record_id.in_(record_ids), f.c.is_current).values(is_current=False)
    )
    now = clock.now()
    for record in conn.execute(select(n).where(n.c.id.in_(record_ids), n.c.is_current)):
        facts = A.allocate(
            amount_micros=record.billed_micros,
            tags=dict(record.tags),
            charge_date=record.charge_date,
            projects=project_refs,
            rules=rules,
            manual_project_id=manual.get((record.source, record.record_key)),
        )
        conn.execute(
            insert(f),
            [
                {
                    "tenant_id": tenant_id,
                    "record_id": record.id,
                    "project_id": fact.project_id,
                    "amount_micros": fact.amount_micros,
                    "currency": record.currency,
                    "state": fact.state,
                    "confidence": fact.confidence,
                    "join_confidence": fact.join_confidence,
                    "rule_id": fact.rule_id,
                    "rule_version": fact.rule_version,
                    "explanation": fact.explanation,
                    "is_current": True,
                    "created_at": now,
                }
                for fact in facts
            ],
        )


def record_batch(
    conn: Connection, tenant_id, source, file_name, data: bytes, result: BatchResult, actor, clock
) -> None:
    conn.execute(
        insert(ingestion_batches).values(
            id=result.batch_id,
            tenant_id=tenant_id,
            source=source,
            file_name=file_name[:200],
            file_sha256=hashlib.sha256(data).digest(),
            status=result.status,
            rows_total=result.rows_total,
            rows_new=result.rows_new,
            rows_revised=result.rows_revised,
            rows_unchanged=result.rows_unchanged,
            reasons=result.reasons,
            actor=actor,
            ingested_at=clock.now(),
        )
    )


def ingest(
    conn: Connection,
    *,
    tenant_id: uuid.UUID,
    source: str,
    file_name: str,
    data: bytes,
    actor: str,
    clock: Clock,
    rng: Rng,
) -> BatchResult:
    """Load one file inside the caller's transaction. Raises Quarantine and loads nothing."""
    if source not in SOURCES:
        raise Quarantine(["Unknown billing source."])
    parsed = parse(data, SOURCES[source])
    raw, n = raw_billing_records, normalized_cost_records
    result = BatchResult(uuid7(clock, rng), "LOADED", rows_total=len(parsed.rows))
    existing = {
        (r.record_key, r.revision): bytes(r.payload_hash)
        for r in conn.execute(
            select(raw.c.record_key, raw.c.revision, raw.c.payload_hash).where(
                raw.c.tenant_id == tenant_id, raw.c.source == source
            )
        )
    }
    latest = dict(
        conn.execute(
            select(raw.c.record_key, func.max(raw.c.revision))
            .where(raw.c.tenant_id == tenant_id, raw.c.source == source)
            .group_by(raw.c.record_key)
        ).all()
    )
    reasons, to_load = [], []
    for row in sorted(parsed.rows, key=lambda r: (r.record_key, r.revision)):
        known = existing.get((row.record_key, row.revision))
        if known is not None:
            if known == payload_hash(row):
                result.rows_unchanged += 1
            else:
                reasons.append(
                    f"Record {row.record_key} revision {row.revision} was loaded before with "
                    "other content. A correction needs a higher revision."
                )
            continue
        if row.revision < latest.get(row.record_key, 0):
            reasons.append(
                f"Record {row.record_key} revision {row.revision} is older than the loaded one."
            )
            continue
        to_load.append(row)
        latest[row.record_key] = row.revision
    if reasons:
        raise Quarantine(reasons)

    record_batch(conn, tenant_id, source, file_name, data, result, actor, clock)
    now = clock.now()
    touched: list[uuid.UUID] = []
    for row in to_load:
        superseded = conn.execute(
            update(n)
            .where(
                n.c.tenant_id == tenant_id, n.c.source == source,
                n.c.record_key == row.record_key, n.c.is_current,
            )
            .values(is_current=False)
            .returning(n.c.id)
        ).all()  # fmt: skip
        if superseded:
            result.rows_revised += 1
            conn.execute(
                update(allocation_facts)
                .where(allocation_facts.c.record_id.in_([r.id for r in superseded]))
                .values(is_current=False)
            )
        else:
            result.rows_new += 1
        raw_id = conn.execute(
            insert(raw)
            .values(
                tenant_id=tenant_id, batch_id=result.batch_id, source=source,
                record_key=row.record_key, revision=row.revision, payload=row.payload(),
                payload_hash=payload_hash(row), ingested_at=now,
            )
            .returning(raw.c.id)
        ).scalar_one()  # fmt: skip
        record_id = uuid7(clock, rng)
        conn.execute(
            insert(n).values(
                id=record_id, tenant_id=tenant_id, raw_id=raw_id, source=source,
                record_key=row.record_key, revision=row.revision, is_current=True,
                provider=row.provider, model_id=row.model_id, charge_date=row.charge_date,
                billing_period=row.billing_period, billed_micros=row.billed_micros,
                currency=row.currency, finalization_state=row.finalization_state,
                consumed_quantity=row.consumed_quantity, consumed_unit=row.consumed_unit,
                tags=row.tags,
            )
        )  # fmt: skip
        touched.append(record_id)
    # If one file carried several revisions of a key, only the highest stays current.
    newest = (
        select(func.max(raw.c.revision))
        .where(
            raw.c.tenant_id == tenant_id,
            raw.c.source == source,
            raw.c.record_key == n.c.record_key,
        )
        .scalar_subquery()
    )
    conn.execute(
        update(n).where(n.c.id.in_(touched), n.c.revision < newest).values(is_current=False)
    )
    reallocate(conn, tenant_id, touched, clock)
    # The batch row was written first (the records refer to it); now it gets its counts.
    conn.execute(
        update(ingestion_batches)
        .where(ingestion_batches.c.id == result.batch_id)
        .values(rows_new=result.rows_new, rows_revised=result.rows_revised,
                rows_unchanged=result.rows_unchanged)
    )  # fmt: skip
    return result
