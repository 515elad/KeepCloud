"""What this gateway instance knows about the ledger's availability.

- A short circuit breaker: after a database failure, the ledger is not tried
  again for a few seconds, so requests do not each wait for a timeout.
- A demo fault switch: makes every ledger write fail while reads still work.
  It exists for the demo console and tests, and cannot be set in production.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from keepair.clock import Clock

RETRY_AFTER_S = 5


class LedgerUnavailable(Exception):
    """The ledger could not be used for this operation."""


class LedgerState:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._retry_at: datetime | None = None
        self.down_since: datetime | None = None
        self.fault_injected = False

    def writes_blocked(self) -> bool:
        return self.fault_injected or self.reads_blocked()

    def reads_blocked(self) -> bool:
        with self._lock:
            return self._retry_at is not None and self._clock.now() < self._retry_at

    def mark_down(self) -> None:
        with self._lock:
            now = self._clock.now()
            self._retry_at = now + timedelta(seconds=RETRY_AFTER_S)
            if self.down_since is None:
                self.down_since = now

    def mark_up(self) -> None:
        with self._lock:
            self._retry_at = None
            self.down_since = None

    def set_fault(self, active: bool) -> None:
        with self._lock:
            self.fault_injected = active
            if active and self.down_since is None:
                self.down_since = self._clock.now()
        if not active:
            self.mark_up()

    @property
    def is_down(self) -> bool:
        return self.down_since is not None
