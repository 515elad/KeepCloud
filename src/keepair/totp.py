"""Time-based one-time passwords (RFC 6238, HMAC-SHA-1, 30 s step, 6 digits).

The time comes from the injected clock, so a code can be checked offline in a
test with a fixed secret and a fixed time (FR-13).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime

from keepair.rng import Rng

STEP_S = 30
DIGITS = 6
WINDOW = 1  # steps accepted on either side of the current one, for clock drift
SECRET_BYTES = 20


def step_of(at: datetime) -> int:
    return int(at.timestamp()) // STEP_S


def code_at_step(secret: bytes, step: int, digits: int = DIGITS) -> str:
    digest = hmac.new(secret, step.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def code(secret: bytes, at: datetime) -> str:
    return code_at_step(secret, step_of(at))


def verify(secret: bytes, candidate: str, at: datetime, last_step: int = 0) -> int | None:
    """The time step the code belongs to, or None when it is not accepted.

    A code is accepted once: its step must be later than ``last_step``, the step
    of the last code this user had accepted.
    """
    candidate = "".join(candidate.split())
    if len(candidate) != DIGITS or not candidate.isdigit():
        return None
    now = step_of(at)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if step > last_step and hmac.compare_digest(code_at_step(secret, step), candidate):
            return step
    return None


def new_secret(rng: Rng) -> bytes:
    return rng.getrandbits(SECRET_BYTES * 8).to_bytes(SECRET_BYTES, "big")


def to_base32(secret: bytes) -> str:
    """The form an authenticator app accepts when the secret is typed in."""
    return base64.b32encode(secret).decode("ascii").rstrip("=")
