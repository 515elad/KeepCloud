"""Background upkeep for a gateway instance (FR-21 heartbeats, FR-05 expiry).

``tick`` is one round. The gateway process runs it every few seconds; tests
call it directly with a fixed clock.

Heartbeats are written only for what was actually seen to work in this round:
- policy_sync: the policy snapshot was reloaded from the database;
- ledger:      the expiry sweep ran against the database (never while it is down);
- alerting:    an alert record could be written and read back;
- gateway:     this round completed.

The round also verifies the audit chain, at start and then once a day (SEC-32).
"""

from __future__ import annotations

import threading
import uuid

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError

from keepair import audit
from keepair.clock import Clock
from keepair.failures import AlertStore, FailureReporter
from keepair.gateway import idempotency, ledger
from keepair.gateway.ledgerstate import LedgerState
from keepair.gateway.replay import replay
from keepair.gateway.snapshot import SnapshotCache
from keepair.gateway.spool import Spool
from keepair.health import record_heartbeat
from keepair.rng import Rng
from keepair.schema import tenants

INTERVAL_S = 5.0
PROLONGED_AFTER_S = 15 * 60  # FR-21: fail-open active over 15 minutes is SEV2
AUDIT_VERIFY_EVERY_S = 24 * 3600  # SEC-32: the audit chain is verified daily


class Maintenance:
    def __init__(
        self,
        engine: Engine,
        clock: Clock,
        snapshots: SnapshotCache,
        store: AlertStore,
        reporter: FailureReporter,
        spool: Spool,
        ledger_state: LedgerState,
        rng: Rng,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._snapshots = snapshots
        self._store = store
        self._reporter = reporter
        self._spool = spool
        self._state = ledger_state
        self._rng = rng
        self._corrupt_reported = 0
        self._audit_verified_at = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _probe_ledger(self) -> bool:
        """Can the ledger be written right now? Clears the breaker when it can."""
        if self._state.fault_injected:
            return False
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError:
            self._state.mark_down()
            return False
        if self._state.is_down:
            self._state.mark_up()
        return True

    def _fail_open_upkeep(self, ledger_up: bool) -> None:
        if self._spool.corrupt_lines > self._corrupt_reported:
            self._corrupt_reported = self._spool.corrupt_lines
            self._reporter.report(
                "SPOOL_CORRUPT",
                f"{self._spool.corrupt_lines} spool lines could not be decrypted and were not "
                "replayed. Spend sent in fail-open may be missing from the ledger.",
            )
        since = self._state.down_since
        if since is not None and (self._clock.now() - since).total_seconds() > PROLONGED_AFTER_S:
            self._reporter.report(
                "FAIL_OPEN_PROLONGED",
                "The ledger has been unreachable for more than 15 minutes. Monitor and soft "
                "budgets are running without a budget check.",
                dedupe_s=PROLONGED_AFTER_S,
            )
        if ledger_up and self._spool.stats().waiting:
            replay(self._engine, self._spool, self._clock, self._rng)

    def _verify_audit_chain(self) -> None:
        """Once at start and then daily (SEC-32). A broken chain is a SEV1 alert."""
        now, last = self._clock.now(), self._audit_verified_at
        if last is not None and (now - last).total_seconds() < AUDIT_VERIFY_EVERY_S:
            return
        with self._engine.connect() as conn:
            result = audit.verify(conn)
        self._audit_verified_at = now
        if not result.ok:
            self._reporter.report(
                "AUDIT_CHAIN_BROKEN",
                f"The daily check of the audit record failed at record {result.broken_at}. "
                f"{result.problem} Treat every record from there on as untrusted.",
            )

    def tick(self) -> dict[str, bool]:
        seen = {"policy_sync": False, "ledger": False, "alerting": False, "gateway": False}
        ledger_up = self._probe_ledger()
        try:
            with self._engine.connect() as conn:
                tenant_ids: list[uuid.UUID] = list(conn.execute(select(tenants.c.id)).scalars())
            seen["policy_sync"] = bool(tenant_ids) and all(
                self._snapshots.refresh(t) for t in tenant_ids
            )
            self._fail_open_upkeep(ledger_up)
            if ledger_up:
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
            self._verify_audit_chain()
            seen["alerting"] = self._store.is_writable()
            seen["gateway"] = True
            with self._engine.begin() as conn:
                for component, ok in seen.items():
                    if ok:
                        record_heartbeat(conn, component, self._clock)
        except SQLAlchemyError:
            self._store.note_db_down()
            self._state.mark_down()
            self._fail_open_upkeep(False)
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
