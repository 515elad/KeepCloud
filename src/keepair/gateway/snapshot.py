"""Policy snapshot cache with the staleness rule (FR-18, SEC-09).

The gateway decides from an immutable in-process snapshot. It is reloaded when
older than ``refresh_after_s``. If a reload fails the old snapshot keeps being
used, but once it is older than ``stale_after_s`` the instance denies every
request: a block added after the snapshot cannot be seen, so nothing is safe.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError

from keepair.clock import Clock
from keepair.gateway.errors import GatewayError
from keepair.gateway.fx import Rate
from keepair.killswitch import active_keys
from keepair.money import MICRO_PER_UNIT
from keepair.registry import PolicySnapshot, load_snapshot
from keepair.schema import fx_rates, vendor_endpoints

REFRESH_AFTER_S = 5
STALE_AFTER_S = 30


@dataclass(frozen=True, slots=True)
class Loaded:
    policy: PolicySnapshot
    endpoints: dict[str, str]
    built_at: datetime
    fx: tuple = ()  # (base, quote, effective_date, rate_micros), newest first
    kill: frozenset = frozenset()  # (scope type, scope id) of every kill switch that is on

    def rate(self, base: str, quote: str, on) -> Rate | None:
        """The rate effective on the given date: the latest one not after it."""
        if base == quote:
            return Rate(base, quote, MICRO_PER_UNIT, None)
        for b, q, effective, rate_micros in self.fx:
            if b == base and q == quote and effective <= on:
                return Rate(base, quote, rate_micros, effective)
        return None


def load_from_database(engine: Engine, tenant_id: uuid.UUID, clock: Clock) -> Loaded:
    with engine.connect() as conn:
        policy = load_snapshot(conn, tenant_id)
        endpoints = dict(
            conn.execute(
                select(vendor_endpoints.c.vendor_id, vendor_endpoints.c.base_url).where(
                    vendor_endpoints.c.tenant_id == tenant_id
                )
            ).all()
        )
        fx = tuple(
            tuple(r)
            for r in conn.execute(
                select(
                    fx_rates.c.base,
                    fx_rates.c.quote,
                    fx_rates.c.effective_date,
                    fx_rates.c.rate_micros,
                ).order_by(fx_rates.c.effective_date.desc())
            )
        )
        kill = active_keys(conn, tenant_id)
    return Loaded(policy, endpoints, clock.now(), fx, kill)


class SnapshotCache:
    def __init__(
        self,
        loader: Callable[[uuid.UUID], Loaded],
        clock: Clock,
        refresh_after_s: int = REFRESH_AFTER_S,
        stale_after_s: int = STALE_AFTER_S,
    ) -> None:
        self._loader = loader
        self._clock = clock
        self._refresh_after_s = refresh_after_s
        self._stale_after_s = stale_after_s
        self._lock = threading.Lock()
        self._current: dict[uuid.UUID, Loaded] = {}

    def refresh(self, tenant_id: uuid.UUID) -> bool:
        """Reload now. Returns False (and keeps the old snapshot) when loading fails."""
        try:
            loaded = self._loader(tenant_id)
        except SQLAlchemyError:
            return False
        with self._lock:
            self._current[tenant_id] = loaded  # swap the reference, never mutate
        return True

    def age_s(self, tenant_id: uuid.UUID) -> float | None:
        current = self._current.get(tenant_id)
        return None if current is None else (self._clock.now() - current.built_at).total_seconds()

    def tenants(self) -> list[uuid.UUID]:
        return list(self._current)

    def get(self, tenant_id: uuid.UUID) -> Loaded:
        age = self.age_s(tenant_id)
        if age is None or age >= self._refresh_after_s:
            self.refresh(tenant_id)
            age = self.age_s(tenant_id)
        if age is None or age > self._stale_after_s:
            raise GatewayError("SNAPSHOT_STALE")
        return self._current[tenant_id]
