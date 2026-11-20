"""Canonical vendor and model registry, and the block decision (FR-18).

The decision is a pure function over an immutable snapshot. Rules:
- an unknown alias or model is denied (default deny);
- a BLOCKED vendor denies every one of its models, whatever the model's status;
- a BLOCKED model is denied whatever the vendor's status;
- allowed needs both the vendor and the model to be ALLOWED.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from sqlalchemy import Connection, insert, select, update

from keepair.clock import Clock
from keepair.schema import model_aliases, models, registry_changes, vendors


class Status(StrEnum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"


class DenyReason(StrEnum):
    VENDOR_BLOCKED = "VENDOR_BLOCKED"
    MODEL_BLOCKED = "MODEL_BLOCKED"
    MODEL_NOT_ALLOWED = "MODEL_NOT_ALLOWED"
    UNKNOWN_MODEL = "UNKNOWN_MODEL"


class EffectiveStatus(StrEnum):
    """What the UI may show for a model (UX-3)."""

    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    BLOCKED_BY_VENDOR = "BLOCKED_BY_VENDOR"


@dataclass(frozen=True, slots=True)
class Pricing:
    input_price_micros_per_1k: int
    output_price_micros_per_1k: int
    currency: str
    max_output_tokens: int
    price_version: int


@dataclass(frozen=True, slots=True)
class ModelEntry:
    vendor_id: str
    status: Status
    pricing: Pricing | None = None


@dataclass(frozen=True, slots=True)
class PolicySnapshot:
    version: int
    vendors: Mapping[str, Status]
    models: Mapping[str, ModelEntry]
    aliases: Mapping[str, str]

    @classmethod
    def build(
        cls,
        version: int,
        vendors: Mapping[str, Status],
        models: Mapping[str, ModelEntry],
        aliases: Mapping[str, str],
    ) -> PolicySnapshot:
        return cls(
            version,
            MappingProxyType(dict(vendors)),
            MappingProxyType(dict(models)),
            MappingProxyType({normalize(k): v for k, v in aliases.items()}),
        )


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: DenyReason | None
    model_id: str | None
    vendor_id: str | None
    snapshot_version: int


def normalize(name: str) -> str:
    return name.strip().lower()


def canonicalize(snapshot: PolicySnapshot, requested: str) -> str | None:
    """Resolve a requested model name to its canonical ID, or None when unknown."""
    name = normalize(requested)
    if name in snapshot.models:
        return name
    return snapshot.aliases.get(name)


def decide_block(snapshot: PolicySnapshot, requested: str) -> Decision:
    def deny(reason: DenyReason, model_id: str | None, vendor_id: str | None) -> Decision:
        return Decision(False, reason, model_id, vendor_id, snapshot.version)

    model_id = canonicalize(snapshot, requested)
    entry = snapshot.models.get(model_id) if model_id else None
    if model_id is None or entry is None:
        return deny(DenyReason.UNKNOWN_MODEL, None, None)
    vendor_status = snapshot.vendors.get(entry.vendor_id)
    if vendor_status is None:
        return deny(DenyReason.UNKNOWN_MODEL, model_id, entry.vendor_id)
    if vendor_status is Status.BLOCKED:
        return deny(DenyReason.VENDOR_BLOCKED, model_id, entry.vendor_id)
    if entry.status is Status.BLOCKED:
        return deny(DenyReason.MODEL_BLOCKED, model_id, entry.vendor_id)
    if entry.status is not Status.ALLOWED or vendor_status is not Status.ALLOWED:
        return deny(DenyReason.MODEL_NOT_ALLOWED, model_id, entry.vendor_id)
    return Decision(True, None, model_id, entry.vendor_id, snapshot.version)


def effective_model_status(vendor_status: Status, model_status: Status) -> EffectiveStatus:
    """effective_status = Blocked by vendor when the vendor is BLOCKED, else the model's own."""
    if vendor_status is not Status.ALLOWED:
        return EffectiveStatus.BLOCKED_BY_VENDOR
    if model_status is not Status.ALLOWED:
        return EffectiveStatus.BLOCKED
    return EffectiveStatus.ALLOWED


# --- Database access -------------------------------------------------------


def load_snapshot(conn: Connection, tenant_id: uuid.UUID) -> PolicySnapshot:
    vendor_rows = conn.execute(
        select(vendors.c.id, vendors.c.status, vendors.c.version).where(
            vendors.c.tenant_id == tenant_id
        )
    ).all()
    model_rows = conn.execute(select(models).where(models.c.tenant_id == tenant_id)).all()
    alias_rows = conn.execute(
        select(model_aliases.c.alias, model_aliases.c.model_id).where(
            model_aliases.c.tenant_id == tenant_id
        )
    ).all()
    version = sum(r.version for r in vendor_rows) + sum(r.version for r in model_rows)
    return PolicySnapshot.build(
        version,
        {r.id: Status(r.status) for r in vendor_rows},
        {
            r.id: ModelEntry(
                r.vendor_id,
                Status(r.status),
                Pricing(
                    r.input_price_micros_per_1k,
                    r.output_price_micros_per_1k,
                    r.price_currency,
                    r.max_output_tokens,
                    r.price_version,
                ),
            )
            for r in model_rows
        },
        {r.alias: r.model_id for r in alias_rows},
    )


class RegistryError(ValueError):
    """A registry change that is not allowed. The message is safe to show."""


REASON_MIN, REASON_MAX = 10, 300


def clean_reason(reason: str) -> str:
    reason = " ".join(reason.split())
    if not REASON_MIN <= len(reason) <= REASON_MAX:
        raise RegistryError(f"Give a reason of {REASON_MIN} to {REASON_MAX} characters.")
    return reason


def add_block(
    conn: Connection,
    tenant_id: uuid.UUID,
    subject_type: str,
    subject_id: str,
    actor: str,
    reason: str,
    clock: Clock,
) -> None:
    """Add a block. One step, any administrator (FR-18). Lifting is a separate, two-person flow."""
    table = {"vendor": vendors, "model": models}.get(subject_type)
    if table is None:
        raise RegistryError("Unknown registry item type.")
    reason = clean_reason(reason)
    row = conn.execute(
        select(table.c.status)
        .where(table.c.tenant_id == tenant_id, table.c.id == subject_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise RegistryError("This registry item does not exist.")
    if row.status == Status.BLOCKED:
        raise RegistryError("This item is already blocked.")
    now = clock.now()
    conn.execute(
        update(table)
        .where(table.c.tenant_id == tenant_id, table.c.id == subject_id)
        .values(status=Status.BLOCKED.value, updated_at=now, version=table.c.version + 1)
    )
    conn.execute(
        insert(registry_changes).values(
            tenant_id=tenant_id,
            subject_type=subject_type,
            subject_id=subject_id,
            before_status=Status.ALLOWED.value,
            after_status=Status.BLOCKED.value,
            actor=actor,
            reason=reason,
            changed_at=now,
        )
    )
