"""Append-only, hash-chained audit record (FR-12, SEC-31, SEC-32).

Every administrative action calls ``record`` inside its own transaction, so an
action and its audit record are stored together or not at all.

    row_hash = SHA-256(prev_hash || canonical(row))

``canonical`` is the row as JSON with sorted keys. The newest link is kept in
``audit_head`` and locked while a record is appended, which puts records in one
order. ``verify`` walks the chain and recomputes every hash.

What this detects: a changed record, a removed record, a record inserted out of
order, and a removed tail (the head no longer matches). What it cannot detect on
its own: someone with full database rights rewriting every record and the head.
That needs a head stored outside the database (SEC-32 external anchor), which is
not built.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection, insert, select, update

from keepair.clock import Clock
from keepair.schema import audit_head, audit_log

GENESIS = bytes(32)


class AuditUnavailable(RuntimeError):
    """The chain head is missing. Nothing may be recorded, so nothing may be done."""


def canonical(fields: dict) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _fields(seq, tenant_id, occurred_at: datetime, actor, actor_id, action, subject_type,
            subject_id, before, after, reason) -> dict:  # fmt: skip
    return {
        "seq": seq,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "occurred_at": occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "actor": actor,
        "actor_id": str(actor_id) if actor_id else None,
        "action": action,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "before": before,
        "after": after,
        "reason": reason,
    }


def row_hash(prev_hash: bytes, fields: dict) -> bytes:
    return hashlib.sha256(prev_hash + canonical(fields)).digest()


def record(
    conn: Connection,
    clock: Clock,
    *,
    tenant_id: uuid.UUID | None,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    actor_id: uuid.UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> int:
    """Append one record. Runs in the caller's transaction."""
    head = conn.execute(select(audit_head).where(audit_head.c.id == 1).with_for_update())
    head = head.one_or_none()
    if head is None:
        raise AuditUnavailable("audit chain head is missing")
    seq = head.seq + 1
    prev = bytes(head.row_hash)
    occurred_at = clock.now()
    fields = _fields(seq, tenant_id, occurred_at, actor, actor_id, action, subject_type,
                     subject_id, before, after, reason)  # fmt: skip
    digest = row_hash(prev, fields)
    conn.execute(
        insert(audit_log).values(
            seq=seq, tenant_id=tenant_id, occurred_at=occurred_at, actor=actor, actor_id=actor_id,
            action=action, subject_type=subject_type, subject_id=subject_id, before=before,
            after=after, reason=reason, prev_hash=prev, row_hash=digest,
        )
    )  # fmt: skip
    conn.execute(update(audit_head).where(audit_head.c.id == 1).values(seq=seq, row_hash=digest))
    return seq


@dataclass(frozen=True, slots=True)
class VerifyResult:
    ok: bool
    checked: int
    head_hash: bytes
    broken_at: int | None = None
    problem: str | None = None


def verify(conn: Connection) -> VerifyResult:
    """Recompute the whole chain. Reads only."""

    def broken(checked: int, prev: bytes, at: int, problem: str) -> VerifyResult:
        return VerifyResult(False, checked, prev, at, problem)

    prev, expected_seq, checked = GENESIS, 1, 0
    for r in conn.execute(select(audit_log).order_by(audit_log.c.seq)):
        if r.seq != expected_seq:
            return broken(checked, prev, expected_seq, f"Record {expected_seq} is missing.")
        if bytes(r.prev_hash) != prev:
            return broken(
                checked, prev, r.seq, f"Record {r.seq} does not follow the record before it."
            )
        fields = _fields(r.seq, r.tenant_id, r.occurred_at, r.actor, r.actor_id, r.action,
                         r.subject_type, r.subject_id, r.before, r.after, r.reason)  # fmt: skip
        if row_hash(prev, fields) != bytes(r.row_hash):
            return broken(checked, prev, r.seq, f"Record {r.seq} was changed after it was written.")
        prev, expected_seq, checked = bytes(r.row_hash), r.seq + 1, checked + 1
    head = conn.execute(select(audit_head).where(audit_head.c.id == 1)).one_or_none()
    if head is None or head.seq != checked or bytes(head.row_hash) != prev:
        return broken(
            checked, prev, checked + 1,
            "The newest records are missing: the chain is shorter than its head.",
        )  # fmt: skip
    return VerifyResult(True, checked, prev)
