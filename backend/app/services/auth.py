from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import Settings
from app.core.security import (
    as_utc,
    csrf_digest,
    csrf_token_for_session,
    hash_password,
    new_session_token,
    normalize_identity,
    private_identifier,
    session_digest,
    session_times,
    utc_now,
    verify_password,
)
from app.models import AuditEvent, LoginThrottle, SessionRecord, User

THROTTLE_WINDOW = timedelta(minutes=15)
THROTTLE_BLOCK = timedelta(minutes=15)
_LOGIN_ATTEMPT_LOCK = Lock()


@contextmanager
def login_attempt_guard() -> Iterator[None]:
    """Serialize login throttle mutation in the required single-worker process."""

    with _LOGIN_ATTEMPT_LOCK:
        yield


@dataclass(slots=True)
class Principal:
    user: User
    session: SessionRecord
    csrf_token: str


def add_audit_event(
    db: Session,
    settings: Settings,
    *,
    action: str,
    outcome: str,
    request_id: str | None,
    user_id: int | None = None,
    identity: str | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            user_id=user_id,
            subject_key=(
                private_identifier(settings, "audit-subject", normalize_identity(identity))
                if identity
                else None
            ),
            action=action,
            outcome=outcome,
            request_id=request_id,
            detail=detail,
            created_at=utc_now(),
        )
    )


def throttle_keys(settings: Settings, identity: str, client_ip: str) -> list[tuple[str, int]]:
    return [
        (private_identifier(settings, "login-identity", normalize_identity(identity)), 5),
        (private_identifier(settings, "login-ip", client_ip), 20),
    ]


def throttled_for(db: Session, keys: list[tuple[str, int]], now: datetime) -> int | None:
    remaining = 0
    for key, _ in keys:
        row = db.get(LoginThrottle, key)
        if row and row.blocked_until and as_utc(row.blocked_until) > now:
            remaining = max(remaining, math.ceil((as_utc(row.blocked_until) - now).total_seconds()))
    return remaining or None


def record_login_failure(db: Session, keys: list[tuple[str, int]], now: datetime) -> None:
    for key, limit in keys:
        row = db.scalar(select(LoginThrottle).where(LoginThrottle.key == key).with_for_update())
        if row is None:
            row = LoginThrottle(
                key=key,
                failed_attempts=0,
                window_started_at=now,
                blocked_until=None,
                updated_at=now,
            )
            db.add(row)
        elif now - as_utc(row.window_started_at) >= THROTTLE_WINDOW:
            row.failed_attempts = 0
            row.window_started_at = now
            row.blocked_until = None

        row.failed_attempts += 1
        row.updated_at = now
        if row.failed_attempts >= limit:
            row.blocked_until = now + THROTTLE_BLOCK


def clear_login_failures(db: Session, keys: list[tuple[str, int]]) -> None:
    # A successful identity clears only that identity's failures. The IP row is
    # an aggregate abuse signal shared by all identities and must not be erased
    # by a single valid login.
    identity_key = keys[0][0]
    db.execute(delete(LoginThrottle).where(LoginThrottle.key == identity_key))


def find_user_for_login(db: Session, identity: str) -> User | None:
    normalized = normalize_identity(identity)
    return db.scalar(
        select(User)
        .options(selectinload(User.settings))
        .where((User.normalized_username == normalized) | (User.normalized_email == normalized))
        .with_for_update()
    )


def check_user_password(user: User | None, password: str) -> tuple[bool, bool]:
    return verify_password(user.password_hash if user else None, password)


def issue_session(
    db: Session,
    settings: Settings,
    user: User,
    *,
    client_ip: str,
    user_agent: str | None = None,
) -> tuple[str, str, SessionRecord]:
    token = new_session_token()
    csrf_token = csrf_token_for_session(settings, token)
    times = session_times()
    record = SessionRecord(
        user_id=user.id,
        token_digest=session_digest(settings, token),
        csrf_digest=csrf_digest(settings, csrf_token),
        created_at=times.created_at,
        last_seen_at=times.created_at,
        idle_expires_at=times.idle_expires_at,
        absolute_expires_at=times.absolute_expires_at,
        revoked_at=None,
        client_key=private_identifier(settings, "session-ip", client_ip),
        user_agent=(user_agent or "").strip()[:512] or None,
    )
    db.add(record)
    db.flush()
    return token, csrf_token, record


def load_principal(
    db: Session, settings: Settings, token: str, now: datetime | None = None
) -> Principal | None:
    current = now or utc_now()
    record = db.scalar(
        select(SessionRecord)
        .options(joinedload(SessionRecord.user).joinedload(User.settings))
        .where(SessionRecord.token_digest == session_digest(settings, token))
    )
    if record is None or record.revoked_at is not None:
        return None
    if as_utc(record.idle_expires_at) <= current or as_utc(record.absolute_expires_at) <= current:
        record.revoked_at = current
        db.commit()
        return None

    last_seen = as_utc(record.last_seen_at)
    if current - last_seen >= timedelta(minutes=5):
        record.last_seen_at = current
        record.idle_expires_at = min(
            current + timedelta(hours=12), as_utc(record.absolute_expires_at)
        )
        db.commit()
    return Principal(
        user=record.user,
        session=record,
        csrf_token=csrf_token_for_session(settings, token),
    )


def revoke_session(db: Session, record: SessionRecord) -> None:
    record.revoked_at = utc_now()


def revoke_user_sessions(db: Session, user_id: int) -> int:
    records = db.scalars(
        select(SessionRecord).where(
            SessionRecord.user_id == user_id, SessionRecord.revoked_at.is_(None)
        )
    ).all()
    now = utc_now()
    for record in records:
        record.revoked_at = now
    return len(records)


def update_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password)
