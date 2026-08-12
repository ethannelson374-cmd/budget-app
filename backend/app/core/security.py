from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore
from typing import Literal

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

SESSION_IDLE = timedelta(hours=12)
SESSION_ABSOLUTE = timedelta(days=7)

PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
_ARGON2_SLOTS = BoundedSemaphore(value=2)
with _ARGON2_SLOTS:
    _DUMMY_HASH = PASSWORD_HASHER.hash("this-password-is-never-a-user-password")


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def normalize_identity(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def hash_password(password: str) -> str:
    with _ARGON2_SLOTS:
        return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str | None, password: str) -> tuple[bool, bool]:
    candidate = password_hash or _DUMMY_HASH
    valid: bool
    try:
        with _ARGON2_SLOTS:
            valid = bool(PASSWORD_HASHER.verify(candidate, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        valid = False
    return valid if password_hash is not None else False, bool(
        valid and PASSWORD_HASHER.check_needs_rehash(candidate)
    )


def _keyed_digest(secret: str, domain: str, value: str) -> str:
    key = hmac.new(
        secret.encode("utf-8"),
        f"budget/v1/key/{domain}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def private_identifier(settings: Settings, domain: str, value: str) -> str:
    return _keyed_digest(settings.secret_value("app_secret"), domain, value)


def session_digest(settings: Settings, token: str) -> str:
    return _keyed_digest(settings.secret_value("session_secret"), "session", token)


def csrf_digest(settings: Settings, token: str) -> str:
    return _keyed_digest(settings.secret_value("session_secret"), "csrf", token)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_token_for_session(settings: Settings, session_token: str) -> str:
    raw = bytes.fromhex(
        _keyed_digest(settings.secret_value("session_secret"), "csrf-token", session_token)
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def constant_time_matches(candidate: str, expected: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(candidate.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


def cookie_name(settings: Settings) -> str:
    return "__Host-budget_session" if settings.is_production else "budget_session"


@dataclass(frozen=True, slots=True)
class SessionTimes:
    created_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


def session_times(now: datetime | None = None) -> SessionTimes:
    created = now or utc_now()
    return SessionTimes(created, created + SESSION_IDLE, created + SESSION_ABSOLUTE)


AuditOutcome = Literal["success", "failure", "blocked"]
