"""Idempotency keys (FR-05). Required on every gateway write.

- Same key, same body, result stored: the stored result is returned. No new reservation.
- Same key, same body, still running: 409 with Retry-After.
- Same key, different body: 422. Never reserves.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert

from keepair.gateway.errors import GatewayError
from keepair.schema import idempotency_keys

_KEY_RE = re.compile(r"[\x21-\x7e]{1,200}")


@dataclass(slots=True)
class Stored:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


def validate_key(key: str | None) -> str:
    if key is None or not _KEY_RE.fullmatch(key):
        raise GatewayError("IDEMPOTENCY_KEY_REQUIRED")
    return key


def begin(
    conn: Connection, tenant_id: uuid.UUID, agent_id: uuid.UUID, key: str, request_hash: bytes
) -> Stored | None:
    """Claim the key. Returns None when this is a new request, or the stored result."""
    t = idempotency_keys
    claimed = conn.execute(
        insert(t)
        .values(agent_id=agent_id, key=key, tenant_id=tenant_id, request_hash=request_hash)
        .on_conflict_do_nothing()
        .returning(t.c.key)
    ).one_or_none()
    if claimed is not None:
        return None
    row = conn.execute(select(t).where(t.c.agent_id == agent_id, t.c.key == key)).one()
    if bytes(row.request_hash) != request_hash:
        raise GatewayError("IDEMPOTENCY_KEY_REUSED")
    if row.response_status is None:
        raise GatewayError("IDEMPOTENCY_IN_FLIGHT", headers={"Retry-After": "2"})
    return Stored(row.response_status, row.response_body)


def finish(conn: Connection, agent_id: uuid.UUID, key: str, status: int, body: dict) -> None:
    t = idempotency_keys
    conn.execute(
        update(t)
        .where(t.c.agent_id == agent_id, t.c.key == key)
        .values(response_status=status, response_body=body)
    )


def forget(conn: Connection, agent_id: uuid.UUID, key: str) -> None:
    t = idempotency_keys
    conn.execute(
        delete(t).where(t.c.agent_id == agent_id, t.c.key == key, t.c.response_status.is_(None))
    )


def sweep(conn: Connection) -> int:
    """Remove keys left in flight by a crash, and stored results older than 24 hours."""
    result = conn.execute(
        text(
            "DELETE FROM idempotency_keys WHERE "
            "(response_status IS NULL AND created_at < now() - interval '10 minutes') "
            "OR created_at < now() - interval '24 hours'"
        )
    )
    return result.rowcount
