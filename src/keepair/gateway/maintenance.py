"""Background upkeep for a gateway instance (FR-21 heartbeats, FR-05 expiry).

``tick`` is one round. The gateway process runs it every few seconds; tests
call it directly with a fixed clock.

Heartbeats are written only for what was actually seen to work in this round:
- policy_sync: the policy snapshot was reloaded from the database;
- ledger:      the expiry sweep ran against the database;
- alerting:    an alert record could be written and read back;
- gateway:     this round completed.
"""

from __future__ import annotations

import threading
import uuid

from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError

from keepair.clock import Clock
from keepair.failures import AlertStore, FailureReporter
from keepair.gateway import idempotency, ledger
from keepair.gateway.snapshot import SnapshotCache
from keepair.health import record_heartbeat
from keepair.schema import tenants

INTERVAL_S = 5.0


class Maintenance:
    def __init__(
        self,
        engine: Engine,
        clock: Clock,
        snapshots: SnapshotCache,
        store: AlertStore,
        reporter: FailureReporter,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._snapshots = snapshots
        self._store = store
        self._reporter = reporter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> dict[str, bool]:
        seen = {"policy_sync": False, "ledger": False, "alerting": False, "gateway": False}
        try:
            with self._engine.connect() as conn:
                tenant_ids: list[uuid.UUID] = list(conn.execute(select(tenants.c.id)).scalars())
            seen["policy_sync"] = bool(tenant_ids) and all(
                self._snapshots.refresh(t) for t in tenant_ids
            )
            with self._engine.begin() as conn:
                expired = ledger.sweep_expired(conn, self._clock)
                idempotency.sweep(conn)
            seen["ledger"] = True
            for item in expired:
                if item.was_state == "RESERVED":
                    self._reporter.report(
                        "RESERVATION_EXPIRED",
                        f"Reservation {item.reservation_id} was not settled in time. It was "
                        "settled at the reserved amount and its real usage is unknown.",
                    )
            seen["alerting"] = self._store.is_writable()
            seen["gateway"] = True
            with self._engine.begin() as conn:
                for component, ok in seen.items():
                    if ok:
                        record_heartbeat(conn, component, self._clock)
        except SQLAlchemyError:
            self._store.note_db_down()
            self._reporter.report(
                "DATABASE_UNREACHABLE",
                "The gateway upkeep round could not reach the database. No heartbeat was written.",
                dedupe_s=60,
            )
        return seen

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(INTERVAL_S)

        self._thread = threading.Thread(target=loop, name="keepair-maintenance", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=INTERVAL_S * 2)
