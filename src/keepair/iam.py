"""Local accounts, sign-in with a password and TOTP, and sessions (FR-13, SEC-13).

Sign-in has two steps. A correct password creates a session that is not yet
usable; a correct authenticator code makes it usable. Only the SHA-256 of the
session token is stored. Sessions end after 30 minutes without use and after
12 hours in any case.

The gateway never calls this module, and this module never reads a gateway
token: the two ways of authenticating share no code path (SEC-14).
"""

from __future__ import annotations

import base64
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Connection, delete, insert, select, update

from keepair import audit, passwords, totp
from keepair.clock import Clock
from keepair.ids import uuid7
from keepair.permissions import Role
from keepair.rng import Rng
from keepair.schema import budgets, sessions, users

IDLE_S = 30 * 60
ABSOLUTE_S = 12 * 3600
PENDING_S = 5 * 60  # time allowed between the password and the code
MAX_FAILED = 5
LOCK_S = 15 * 60
COOKIE = "keepair_session"
_USERNAME = re.compile(r"[a-z][a-z0-9._-]{2,39}")
# Used when no key is configured outside production. Demo material: production
# refuses to start without its own key (SEC-23).
DEV_MFA_KEY = hashlib.sha256(b"keepair demo mfa key, not for production").digest()
_DUMMY_HASH = passwords.hash_password("no-such-user-password", bytes(16))


class IamError(ValueError):
    """A refused account change. The message is safe to show."""


class MissingMfaKey(RuntimeError):
    """Production was started without a key for the stored TOTP secrets."""


@dataclass(frozen=True, slots=True)
class Actor:
    id: uuid.UUID
    tenant_id: uuid.UUID
    username: str
    display_name: str
    role: Role


def load_mfa_key(setting: str | None, env: str) -> bytes:
    if setting:
        key = base64.b64decode(setting)
        if len(key) != 32:
            raise MissingMfaKey("KEEPAIR_MFA_KEY must be 32 bytes, base64 encoded")
        return key
    if env == "prod":
        raise MissingMfaKey("KEEPAIR_MFA_KEY is required in production")
    return DEV_MFA_KEY


class SecretBox:
    """AES-256-GCM for the stored TOTP secrets. The user ID is bound to the ciphertext."""

    def __init__(self, key: bytes) -> None:
        self._aead = AESGCM(key)

    def seal(self, secret: bytes, user_id: uuid.UUID, rng: Rng) -> bytes:
        nonce = rng.getrandbits(96).to_bytes(12, "big")
        return nonce + self._aead.encrypt(nonce, secret, user_id.bytes)

    def open(self, blob: bytes, user_id: uuid.UUID) -> bytes | None:
        blob = bytes(blob)
        try:
            return self._aead.decrypt(blob[:12], blob[12:], user_id.bytes)
        except (InvalidTag, ValueError):
            return None


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _new_token(rng: Rng) -> str:
    return base64.urlsafe_b64encode(rng.getrandbits(256).to_bytes(32, "big")).decode().rstrip("=")


def _fail(conn: Connection, clock: Clock, user, what: str) -> None:
    attempts = user.failed_attempts + 1
    values: dict = {"failed_attempts": attempts}
    if attempts >= MAX_FAILED:
        values = {"failed_attempts": 0, "locked_until": clock.now() + timedelta(seconds=LOCK_S)}
    conn.execute(update(users).where(users.c.id == user.id).values(**values))
    audit.record(
        conn, clock, tenant_id=user.tenant_id, actor=user.username, actor_id=user.id,
        action="auth.sign_in_failed", subject_type="user", subject_id=user.username,
        after={"step": what, "locked": attempts >= MAX_FAILED},
    )  # fmt: skip


def _usable(user, clock: Clock) -> bool:
    locked = user.locked_until is not None and user.locked_until > clock.now()
    return user.status == "ACTIVE" and not locked


def sign_in_password(
    conn: Connection, clock: Clock, rng: Rng, username: str, password: str
) -> str | None:
    """Step one. Returns a token for a session that still needs the code, or None.

    The answer is the same for an unknown user, a wrong password, a disabled
    account and a locked account, and costs the same time.
    """
    name = username.strip().lower()
    user = conn.execute(select(users).where(users.c.username == name).limit(1)).one_or_none()
    if user is None:
        passwords.verify_password(password, _DUMMY_HASH)
        return None
    correct = passwords.verify_password(password, user.password_hash)
    if not _usable(user, clock):
        return None
    if not correct:
        _fail(conn, clock, user, "password")
        return None
    token, now = _new_token(rng), clock.now()
    conn.execute(
        insert(sessions).values(
            token_hash=_hash(token), user_id=user.id, created_at=now, last_seen_at=now,
            mfa_verified=False,
        )
    )  # fmt: skip
    return token


def _session(conn: Connection, token: str | None):
    if not token or len(token) > 100:
        return None
    return conn.execute(
        select(
            sessions.c.user_id, sessions.c.created_at, sessions.c.last_seen_at,
            sessions.c.mfa_verified, users.c.tenant_id, users.c.username, users.c.display_name,
            users.c.role, users.c.status, users.c.locked_until,
        )
        .select_from(sessions.join(users, users.c.id == sessions.c.user_id))
        .where(sessions.c.token_hash == _hash(token))
    ).one_or_none()  # fmt: skip


def is_locked(conn: Connection, clock: Clock, username: str) -> bool:
    locked_until = conn.execute(
        select(users.c.locked_until).where(users.c.username == username.strip().lower())
    ).scalar_one_or_none()
    return locked_until is not None and locked_until > clock.now()


def pending_username(conn: Connection, clock: Clock, token: str | None) -> str | None:
    """The user who gave a correct password and now owes the code."""
    row = _session(conn, token)
    if row is None or row.mfa_verified:
        return None
    if (clock.now() - row.created_at).total_seconds() > PENDING_S:
        return None
    return row.username


def _accept_code(conn, clock: Clock, box: SecretBox, user, candidate: str) -> bool:
    secret = box.open(user.totp_secret_enc, user.id)
    step = totp.verify(secret, candidate, clock.now(), user.totp_last_step) if secret else None
    if step is None:
        return False
    conn.execute(
        update(users).where(users.c.id == user.id).values(totp_last_step=step, failed_attempts=0)
    )
    return True


def _actor(row) -> Actor:
    return Actor(row.user_id, row.tenant_id, row.username, row.display_name, Role(row.role))


def sign_in_code(
    conn: Connection, clock: Clock, box: SecretBox, token: str | None, candidate: str
) -> Actor | None:
    """Step two. Makes the session usable when the authenticator code is right."""
    row = _session(conn, token)
    if row is None or row.mfa_verified or not _usable(row, clock):
        return None
    if (clock.now() - row.created_at).total_seconds() > PENDING_S:
        return None
    user = conn.execute(select(users).where(users.c.id == row.user_id).with_for_update()).one()
    if not _accept_code(conn, clock, box, user, candidate):
        _fail(conn, clock, user, "code")
        return None
    now = clock.now()
    conn.execute(
        update(sessions)
        .where(sessions.c.token_hash == _hash(token))
        .values(mfa_verified=True, created_at=now, last_seen_at=now)
    )
    audit.record(
        conn, clock, tenant_id=user.tenant_id, actor=user.username, actor_id=user.id,
        action="auth.sign_in", subject_type="user", subject_id=user.username,
    )  # fmt: skip
    return _actor(row)


def authenticate(conn: Connection, clock: Clock, token: str | None) -> Actor | None:
    """The signed-in user for a session token, or None. Enforces both time limits."""
    row = _session(conn, token)
    if row is None or not row.mfa_verified or row.status != "ACTIVE":
        return None
    now = clock.now()
    idle = (now - row.last_seen_at).total_seconds()
    age = (now - row.created_at).total_seconds()
    if idle > IDLE_S or age > ABSOLUTE_S:
        conn.execute(delete(sessions).where(sessions.c.token_hash == _hash(token)))
        return None
    if idle >= 60:  # one write a minute is enough to keep the idle limit honest
        conn.execute(
            update(sessions).where(sessions.c.token_hash == _hash(token)).values(last_seen_at=now)
        )
    return _actor(row)


def create_session(conn: Connection, clock: Clock, rng: Rng, user_id: uuid.UUID) -> str:
    """A usable session without the sign-in steps. For the demo seed's tests only."""
    token, now = _new_token(rng), clock.now()
    conn.execute(
        insert(sessions).values(
            token_hash=_hash(token), user_id=user_id, created_at=now, last_seen_at=now,
            mfa_verified=True,
        )
    )  # fmt: skip
    return token


def sign_out(conn: Connection, clock: Clock, token: str | None, actor: Actor | None) -> None:
    if token:
        conn.execute(delete(sessions).where(sessions.c.token_hash == _hash(token)))
    if actor:
        audit.record(
            conn, clock, tenant_id=actor.tenant_id, actor=actor.username, actor_id=actor.id,
            action="auth.sign_out", subject_type="user", subject_id=actor.username,
        )  # fmt: skip


def step_up(conn: Connection, clock: Clock, box: SecretBox, actor: Actor, candidate: str) -> bool:
    """A fresh authenticator code for a sensitive action (SEC-13). Accepted once."""
    user = conn.execute(select(users).where(users.c.id == actor.id).with_for_update()).one()
    if not _usable(user, clock):
        return False
    if _accept_code(conn, clock, box, user, candidate):
        return True
    _fail(conn, clock, user, "step-up")
    return False


def demo_code(conn: Connection, clock: Clock, box: SecretBox, user_id: uuid.UUID) -> str | None:
    """The code a demo user's authenticator would show now. Demo mode only.

    If the current code was already used, the next one is shown: it is accepted
    because codes one step ahead are allowed for clock drift.
    """
    user = conn.execute(select(users).where(users.c.id == user_id)).one_or_none()
    secret = box.open(user.totp_secret_enc, user.id) if user else None
    if secret is None:
        return None
    step = max(totp.step_of(clock.now()), user.totp_last_step + 1)
    if step > totp.step_of(clock.now()) + totp.WINDOW:
        return None
    return totp.code_at_step(secret, step)


# --- Account administration -----------------------------------------------------


def _clean_name(display_name: str) -> str:
    name = " ".join(display_name.split())
    if not 1 <= len(name) <= 80 or not name.isprintable():
        raise IamError("Give a display name of 1 to 80 characters.")
    return name


@dataclass(frozen=True, slots=True)
class NewCredentials:
    user_id: uuid.UUID
    username: str
    password: str
    totp_secret: str  # base32, shown once


def _issue(conn, rng: Rng, box: SecretBox, user_id: uuid.UUID) -> tuple[str, bytes, str, str]:
    password, secret = passwords.generate_password(rng), totp.new_secret(rng)
    hashed = passwords.hash_password(password, passwords.new_salt(rng))
    return password, box.seal(secret, user_id, rng), hashed, totp.to_base32(secret)


def create_user(
    conn: Connection, clock: Clock, rng: Rng, box: SecretBox, *, tenant_id: uuid.UUID,
    username: str, display_name: str, role: str, actor: Actor,
) -> NewCredentials:  # fmt: skip
    name = username.strip().lower()
    if not _USERNAME.fullmatch(name):
        raise IamError(
            "A user name is 3 to 40 characters: lower-case letters, digits, dot, dash or "
            "underscore, starting with a letter."
        )
    if role not in Role.__members__:
        raise IamError("Choose one of the listed roles.")
    shown = _clean_name(display_name)
    taken = conn.execute(
        select(users.c.id).where(users.c.tenant_id == tenant_id, users.c.username == name)
    ).one_or_none()
    if taken is not None:
        raise IamError("This user name is already taken.")
    user_id = uuid7(clock, rng)
    password, sealed, hashed, secret_b32 = _issue(conn, rng, box, user_id)
    conn.execute(
        insert(users).values(
            id=user_id, tenant_id=tenant_id, username=name, display_name=shown, role=role,
            status="ACTIVE", password_hash=hashed, totp_secret_enc=sealed,
            created_at=clock.now(), created_by=actor.username,
        )
    )  # fmt: skip
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor.username, actor_id=actor.id,
        action="user.created", subject_type="user", subject_id=name,
        after={"role": role, "display_name": shown, "status": "ACTIVE"},
    )  # fmt: skip
    return NewCredentials(user_id, name, password, secret_b32)


def _target(conn: Connection, tenant_id: uuid.UUID, user_id: uuid.UUID):
    user = conn.execute(
        select(users).where(users.c.id == user_id, users.c.tenant_id == tenant_id).with_for_update()
    ).one_or_none()
    if user is None:
        raise IamError("This user does not exist.")
    return user


def set_status(
    conn: Connection, clock: Clock, *, tenant_id: uuid.UUID, user_id: uuid.UUID, status: str,
    actor: Actor,
) -> None:  # fmt: skip
    user = _target(conn, tenant_id, user_id)
    if status not in ("ACTIVE", "DISABLED") or status == user.status:
        raise IamError("The account is already in that state.")
    if status == "DISABLED":
        if user.id == actor.id:
            raise IamError("You cannot disable your own account.")
        owns_hard = conn.execute(
            select(budgets.c.id).where(
                budgets.c.owner_user_id == user.id, budgets.c.policy == "HARD"
            )
        ).first()
        if owns_hard is not None:
            raise IamError(
                "This user owns a hard-limit budget. Assign another owner first (FR-17)."
            )
        conn.execute(delete(sessions).where(sessions.c.user_id == user.id))
    conn.execute(
        update(users)
        .where(users.c.id == user.id)
        .values(status=status, failed_attempts=0, locked_until=None)
    )
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor.username, actor_id=actor.id,
        action="user.disabled" if status == "DISABLED" else "user.enabled",
        subject_type="user", subject_id=user.username,
        before={"status": user.status}, after={"status": status},
    )  # fmt: skip


def reset_credentials(
    conn: Connection, clock: Clock, rng: Rng, box: SecretBox, *, tenant_id: uuid.UUID,
    user_id: uuid.UUID, actor: Actor,
) -> NewCredentials:  # fmt: skip
    """New password and new TOTP secret, shown once. Ends the user's sessions."""
    user = _target(conn, tenant_id, user_id)
    password, sealed, hashed, secret_b32 = _issue(conn, rng, box, user.id)
    conn.execute(
        update(users)
        .where(users.c.id == user.id)
        .values(password_hash=hashed, totp_secret_enc=sealed, totp_last_step=0,
                failed_attempts=0, locked_until=None)
    )  # fmt: skip
    conn.execute(delete(sessions).where(sessions.c.user_id == user.id))
    audit.record(
        conn, clock, tenant_id=tenant_id, actor=actor.username, actor_id=actor.id,
        action="user.credentials_reset", subject_type="user", subject_id=user.username,
    )  # fmt: skip
    return NewCredentials(user.id, user.username, password, secret_b32)
