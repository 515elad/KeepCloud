"""Failure visibility (hard rule 5, SEC-36).

Every failure path calls ``FailureReporter.report``. That increments a metric
and stores an alert record; the Overview page lists alert records. Nothing is
caught and dropped.

If the database itself is the thing that failed, the alert is held in memory
and shown from there, then written to the database once it is reachable again.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import SQLAlchemyError

from keepair.clock import Clock
from keepair.metrics import Metrics
from keepair.schema import alerts

FAILURES_TOTAL = "keepair_failures_total"
ALERT_FALLBACK_TOTAL = "keepair_alert_store_fallback_total"

# The enumerated list of failure paths. tests/system/test_failure_visibility.py
# fails if a code here has no test that proves metric + alert + UI row.
FAILURE_CODES: dict[str, tuple[str, str]] = {
    # code: (severity, component)
    "DATABASE_UNREACHABLE": ("SEV2", "ledger"),
    "UNHANDLED_ERROR": ("SEV3", "app"),
}

_MEMORY_LIMIT = 100
_RETRY_AFTER = timedelta(seconds=5)


@dataclass(frozen=True, slots=True)
class Alert:
    raised_at: datetime
    severity: str
    code: str
    component: str
    message: str
    id: int | None = None
    held_in_memory: bool = False


class AlertStore:
    def __init__(self, engine: Engine, clock: Clock, metrics: Metrics) -> None:
        self._engine = engine
        self._clock = clock
        self._metrics = metrics
        self._memory: OrderedDict[tuple[str, str], Alert] = OrderedDict()
        self._db_retry_at: datetime | None = None

    def _db_allowed(self) -> bool:
        return self._db_retry_at is None or self._clock.now() >= self._db_retry_at

    def _mark_db_down(self) -> None:
        self._db_retry_at = self._clock.now() + _RETRY_AFTER

    def note_db_down(self) -> None:
        """Called by code that has just seen the database fail."""
        self._mark_db_down()

    def _hold(self, alert: Alert) -> Alert:
        held = replace(alert, held_in_memory=True)
        key = (alert.code, alert.component)
        self._memory.pop(key, None)
        self._memory[key] = held
        while len(self._memory) > _MEMORY_LIMIT:
            self._memory.popitem(last=False)
        self._metrics.inc(ALERT_FALLBACK_TOTAL)
        return held

    def add(self, alert: Alert) -> Alert:
        if self._db_allowed():
            try:
                with self._engine.begin() as conn:
                    self._insert(conn, alert)
                self._db_retry_at = None
                return alert
            except SQLAlchemyError:
                self._mark_db_down()
        return self._hold(alert)

    @staticmethod
    def _insert(conn, alert: Alert) -> None:
        conn.execute(
            insert(alerts).values(
                raised_at=alert.raised_at,
                severity=alert.severity,
                code=alert.code,
                component=alert.component,
                message=alert.message,
            )
        )

    def recent(self, limit: int = 50) -> list[Alert]:
        stored: list[Alert] = []
        if self._db_allowed():
            try:
                with self._engine.begin() as conn:
                    for held in list(self._memory.values()):
                        self._insert(conn, held)
                    self._memory.clear()
                    rows = conn.execute(
                        select(alerts)
                        .order_by(alerts.c.raised_at.desc(), alerts.c.id.desc())
                        .limit(limit)
                    )
                    stored = [
                        Alert(r.raised_at, r.severity, r.code, r.component, r.message, id=r.id)
                        for r in rows
                    ]
                self._db_retry_at = None
            except SQLAlchemyError:
                self._mark_db_down()
        held_now = sorted(self._memory.values(), key=lambda a: a.raised_at, reverse=True)
        return (held_now + stored)[:limit]


class FailureReporter:
    def __init__(self, store: AlertStore, metrics: Metrics, clock: Clock) -> None:
        self._store = store
        self._metrics = metrics
        self._clock = clock
        metrics.describe(FAILURES_TOTAL, "Failures by reason code.")
        metrics.describe(
            ALERT_FALLBACK_TOTAL, "Alerts held in memory because the database was unreachable."
        )

    def report(self, code: str, message: str) -> Alert:
        if code not in FAILURE_CODES:
            raise ValueError(f"unregistered failure code: {code}")
        severity, component = FAILURE_CODES[code]
        self._metrics.inc(FAILURES_TOTAL, code=code)
        return self._store.add(
            Alert(
                raised_at=self._clock.now(),
                severity=severity,
                code=code,
                component=component,
                message=message,
            )
        )
