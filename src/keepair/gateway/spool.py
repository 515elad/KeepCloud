"""Encrypted local spool for fail-open usage (SEC-06, SD-04 default).

When the ledger cannot be written, a request on a monitor or soft budget may
be sent only after a record of it is in this spool. The spool is:

- append-only: one encrypted line per event, flushed to disk before returning;
- encrypted: AES-256-GCM per line, so the file reveals nothing and a changed
  line is detected and never trusted;
- capped: by number of waiting records, by file size and by the age of the
  oldest waiting record. At a cap, ``open_record`` raises and the request is denied.

A record holds metadata only (who, which model, how much). Never a prompt or a response.

Line kinds:  open (before dispatch) -> done (after the answer) -> replayed
             denied (a refusal that could not be written to the decision record)
"""

from __future__ import annotations

import base64
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from keepair.clock import Clock, from_iso, to_iso
from keepair.rng import Rng

FILE_NAME = "fail-open.spool"
_AAD = b"keepair-spool-v1"


class SpoolFull(Exception):
    """A cap is reached. The request must be denied."""


class SpoolError(Exception):
    """The record could not be written safely. The request must be denied."""


@dataclass(frozen=True, slots=True)
class Caps:
    max_records: int = 10_000
    max_bytes: int = 100 * 1024 * 1024  # proposed in PRD v1.5: 100 MB
    max_age_s: int = 3600  # proposed in PRD v1.5: one hour


@dataclass(slots=True)
class Entry:
    id: str
    kind: str  # "usage" or "denied"
    opened_at: datetime
    data: dict[str, Any]
    done: dict[str, Any] | None = None
    claimed: bool = False
    in_flight: bool = False
    replayed: bool = False


@dataclass(slots=True)
class Stats:
    waiting: int = 0
    waiting_usage: int = 0
    bytes: int = 0
    oldest_at: datetime | None = None
    corrupt_lines: int = 0
    caps: Caps = field(default_factory=Caps)


def load_key(configured: str | None, env: str, rng: Rng) -> tuple[bytes, bool]:
    """Return (key, ephemeral). Production needs a configured key; others may use a throwaway."""
    if configured:
        key = base64.b64decode(configured, validate=True)
        if len(key) != 32:
            raise ValueError("KEEPAIR_SPOOL_KEY must be 32 bytes, base64 encoded")
        return key, False
    if env == "prod":
        raise ValueError("KEEPAIR_SPOOL_KEY is required in production")
    return rng.getrandbits(256).to_bytes(32, "big"), True


class Spool:
    def __init__(
        self, directory: Path, key: bytes, clock: Clock, rng: Rng, caps: Caps | None = None
    ) -> None:
        self._path = Path(directory) / FILE_NAME
        self._aead = AESGCM(key)
        self._clock = clock
        self._rng = rng
        self._caps = caps or Caps()
        self._lock = threading.Lock()
        self._entries: dict[str, Entry] = {}
        self._keys: set[tuple[str, str]] = set()
        self._bytes = 0
        self.corrupt_lines = 0
        self._usable = True
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load()
        except OSError:
            # No usable folder: the gateway still runs, but nothing can fail open.
            self._usable = False

    # ------------------------------------------------------------- file layer

    def _seal(self, payload: dict[str, Any]) -> bytes:
        nonce = self._rng.getrandbits(96).to_bytes(12, "big")
        plain = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.b64encode(nonce + self._aead.encrypt(nonce, plain, _AAD)) + b"\n"

    def _unseal(self, line: bytes) -> dict[str, Any] | None:
        try:
            raw = base64.b64decode(line.strip(), validate=True)
            return json.loads(self._aead.decrypt(raw[:12], raw[12:], _AAD))
        except (ValueError, InvalidTag):
            return None

    def _append(self, payload: dict[str, Any]) -> None:
        if not self._usable:
            raise SpoolError("the spool folder cannot be used")
        line = self._seal(payload)
        try:
            with open(self._path, "ab") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise SpoolError("the spool could not be written") from exc
        self._bytes += len(line)

    def _load(self) -> None:
        if not self._path.exists():
            return
        with open(self._path, "rb") as handle:
            for line in handle:
                self._bytes += len(line)
                payload = self._unseal(line)
                if payload is None:
                    self.corrupt_lines += 1  # changed or written with another key: not trusted
                    continue
                self._apply(payload)

    def _apply(self, payload: dict[str, Any]) -> None:
        kind, record_id = payload["t"], payload["id"]
        if kind in ("open", "denied"):
            entry = Entry(
                id=record_id,
                kind="usage" if kind == "open" else "denied",
                opened_at=from_iso(payload["at"]),
                data=payload["data"],
            )
            self._entries[record_id] = entry
            if payload["data"].get("idempotency_key"):
                self._keys.add((payload["data"]["agent_id"], payload["data"]["idempotency_key"]))
        elif record_id in self._entries:
            entry = self._entries[record_id]
            if kind == "done":
                entry.done = payload["data"]
            elif kind == "replayed":
                entry.replayed = True

    # ------------------------------------------------------------ public API

    def _waiting(self) -> list[Entry]:
        return [e for e in self._entries.values() if not e.replayed]

    def _check_caps(self) -> None:
        waiting = self._waiting()
        if len(waiting) >= self._caps.max_records or self._bytes >= self._caps.max_bytes:
            raise SpoolFull("the spool is full")
        if waiting:
            oldest = min(e.opened_at for e in waiting)
            if (self._clock.now() - oldest).total_seconds() > self._caps.max_age_s:
                raise SpoolFull("the fail-open window is used up")

    def open_record(self, record_id: str, data: dict[str, Any]) -> None:
        """Write the record of a request about to be sent. Raises if it cannot be kept."""
        with self._lock:
            self._check_caps()
            payload = {"t": "open", "id": record_id, "at": to_iso(self._clock.now()), "data": data}
            self._append(payload)
            self._apply(payload)
            self._entries[record_id].in_flight = True

    def add_denial(self, record_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._check_caps()
            payload = {
                "t": "denied",
                "id": record_id,
                "at": to_iso(self._clock.now()),
                "data": data,
            }
            self._append(payload)
            self._apply(payload)

    def claim(self, record_id: str) -> bool:
        """Mark an open record as dispatched. False when there is none: nothing may be sent."""
        with self._lock:
            entry = self._entries.get(record_id)
            if (
                entry is None
                or entry.kind != "usage"
                or entry.claimed
                or entry.done
                or entry.replayed
            ):
                return False
            entry.claimed = True
            return True

    def complete(self, record_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            entry = self._entries[record_id]
            entry.in_flight = False
            payload = {"t": "done", "id": record_id, "at": to_iso(self._clock.now()), "data": data}
            self._append(payload)
            self._apply(payload)

    def abandon(self, record_id: str) -> None:
        """The request stopped without an answer being recorded. Replay will use the estimate."""
        with self._lock:
            if record_id in self._entries:
                self._entries[record_id].in_flight = False

    def has_key(self, agent_id: str, key: str) -> bool:
        with self._lock:
            return (agent_id, key) in self._keys

    def pending(self) -> list[Entry]:
        """Records ready for replay, oldest first. Requests still running are left out."""
        with self._lock:
            ready = [e for e in self._waiting() if not e.in_flight]
            return sorted(ready, key=lambda e: (e.opened_at, e.id))

    def mark_replayed(self, record_id: str) -> None:
        with self._lock:
            payload = {"t": "replayed", "id": record_id, "at": to_iso(self._clock.now())}
            self._append(payload)
            self._apply(payload)

    def compact(self) -> bool:
        """Empty the file once nothing is waiting. Returns True when it did."""
        with self._lock:
            if self._waiting():
                return False
            try:
                with open(self._path, "wb") as handle:
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise SpoolError("the spool could not be emptied") from exc
            self._entries.clear()
            self._keys.clear()
            self._bytes = 0
            return True

    def stats(self) -> Stats:
        with self._lock:
            waiting = self._waiting()
            return Stats(
                waiting=len(waiting),
                waiting_usage=sum(1 for e in waiting if e.kind == "usage"),
                bytes=self._bytes,
                oldest_at=min((e.opened_at for e in waiting), default=None),
                corrupt_lines=self.corrupt_lines,
                caps=self._caps,
            )
