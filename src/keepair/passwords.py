"""Password storage and rules (SEC-13, NIST SP 800-63B).

Stored as a salted scrypt hash with its parameters. Rules follow NIST: a length
range, a list of refused common passwords, and no composition rules.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from functools import lru_cache

from keepair.rng import Rng

MIN_LENGTH, MAX_LENGTH = 12, 128
# scrypt cost: N = 2^15, r = 8, p = 3 (an OWASP-listed setting).
LOG_N, R, P = 15, 8, 3
_KEY_LEN = 32
_COMMON = frozenset(
    {
        "password1234",
        "123456789012",
        "qwertyuiopas",
        "letmein12345",
        "administrator",
        "keepairkeepair",
    }
)


class WeakPassword(ValueError):
    """The message is safe to show."""


def check_rules(password: str, username: str = "") -> None:
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise WeakPassword(f"Use {MIN_LENGTH} to {MAX_LENGTH} characters.")
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) < 4:
        raise WeakPassword("This password is too common or too repetitive.")
    if username and username.lower() in lowered:
        raise WeakPassword("The password must not contain the user name.")


@lru_cache(maxsize=64)
def _derive(password: str, salt: bytes, log_n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**log_n, r=r, p=p, dklen=_KEY_LEN,
        maxmem=2 ** (log_n + 8) * r,
    )  # fmt: skip


def new_salt(rng: Rng) -> bytes:
    return rng.getrandbits(128).to_bytes(16, "big")


def hash_password(password: str, salt: bytes) -> str:
    key = _derive(password, salt, LOG_N, R, P)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${LOG_N}${R}${P}${b64(salt)}${b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, log_n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt" or len(password) > MAX_LENGTH:
            return False
        expected = base64.b64decode(key)
        actual = _derive.__wrapped__(password, base64.b64decode(salt), int(log_n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def generate_password(rng: Rng) -> str:
    """An initial password, shown once: 20 characters without look-alikes."""
    # The characters a generated password is drawn from. Not a secret.
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"  # pragma: allowlist secret
    return "".join(alphabet[rng.randrange(len(alphabet))] for _ in range(20))
