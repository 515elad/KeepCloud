"""Gateway tokens (SEC-12, SEC-22, hard rule 8).

A token is 256 random bits, shown once when created. Only its SHA-256 hash is
stored. The fixed prefix and the checksum let secret scanners recognize a
leaked token without a database lookup.

Format:  kair_<43 base62 characters>_<6 character checksum>
"""

from __future__ import annotations

import hashlib
import re
import zlib

from keepair.rng import Rng

PREFIX = "kair_"
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_BODY_LEN = 43  # 62^43 > 2^256
TOKEN_RE = re.compile(r"kair_[0-9A-Za-z]{43}_[0-9A-Za-z]{6}")


def _base62(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, digit = divmod(value, 62)
        chars.append(_ALPHABET[digit])
    return "".join(reversed(chars))


def _checksum(body: str) -> str:
    return _base62(zlib.crc32(body.encode()), 6)


def generate_token(rng: Rng) -> str:
    body = _base62(rng.getrandbits(256), _BODY_LEN)
    return f"{PREFIX}{body}_{_checksum(body)}"


def is_well_formed(token: str) -> bool:
    if not TOKEN_RE.fullmatch(token):
        return False
    body, checksum = token[len(PREFIX) :].split("_")
    return _checksum(body) == checksum


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
