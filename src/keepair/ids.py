"""UUIDv7 identifiers (PRD v1.4 Section 2.3): time-ordered, from injected clock and RNG."""

from __future__ import annotations

import uuid

from keepair.clock import Clock
from keepair.rng import Rng


def uuid7(clock: Clock, rng: Rng) -> uuid.UUID:
    unix_ms = int(clock.now().timestamp() * 1000) & ((1 << 48) - 1)
    rand_a = rng.getrandbits(12)
    rand_b = rng.getrandbits(62)
    value = (unix_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)
