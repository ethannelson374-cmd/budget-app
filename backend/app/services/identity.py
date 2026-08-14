from __future__ import annotations

import json
import re
import secrets
from datetime import timedelta
from typing import cast

from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.credential_crypto import decrypt_user_secret, encrypt_user_secret
from app.core.errors import ApiError
from app.core.security import (
    as_utc,
    hash_password,
    normalize_identity,
    private_identifier,
    utc_now,
    verify_password,
)
from app.core.totp import new_totp_secret, otpauth_uri, verify_totp
from app.integrations.google_oidc import GoogleIdentity, authorization_url
from app.models import (
    AuthIdentity,
    Category,
    OAuthState,
    PasswordResetToken,
    SessionRecord,
    TwoFactorChallenge,
    User,
    UserInvitation,
    UserSettings,
    UserTotp,
)
from app.services.auth import revoke_user_sessions
from app.services.catalog import DEFAULT_CATEGORIES
from app.services.email_delivery import (
    EmailDeliveryError,
    invitation_email,
    password_reset_email,
    send_email,
)

INVITATION_TTL = timedelta(days=7)
PASSWORD_RESET_TTL = timedelta(minutes=30)
OAUTH_STATE_TTL = timedelta(minutes=10)
TWO_FACTOR_CHALLENGE_TTL = timedelta(minutes=5)
RECOVERY_CODE_COUNT = 8


def _token_digest(settings: Settings, domain: str, token: str) -> str:
    return private_identifier(settings, domain, token)


def _active_invitation(invitation: UserInvitation, now=None) -> bool:
    current = now or utc_now()
    return (
        invitation.accepted_at is None
        and invitation.revoked_at is None
        and as_utc(invitation.expires_at) > current
    )


def invitation_status(invitation: UserInvitation) -> str:
    if invitation.accepted_at is not None:
        return "accepted"
    if invitation.revoked_at is not None:
        return "revoked"
    if as_utc(invitation.expires_at) <= utc_now():
        return "expired"
    return "pending"


def invitation_view(
    invitation: UserInvitation,
    *,
    delivery: str | None = None,
    invite_url: str | None = None,
) -> dict[str, object]:
    return {
        "id": invitation.id,
        "email": invitation.email,
        "status": invitation_status(invitation),
        "created_at": invitation.created_at,
        "expires_at": invitation.expires_at,
        "accepted_at": invitation.accepted_at,
        "revoked_at": invitation.revoked_at,
        "delivery": delivery,
        "invite_url": invite_url,
    }


def _require_admin(user: User) -> None:
    if not user.is_admin:
        raise ApiError(403, "admin_required", "Administrator access is required")


def _new_user_settings(source: User | None = None) -> UserSettings:
    if source is not None and source.settings is not None:
        currency = source.settings.currency
        timezone = source.settings.timezone
        theme = source.settings.theme
    else:
        currency, timezone, theme = "USD", "UTC", "system"
    return UserSettings(
        currency=currency,
        timezone=timezone,
        theme=theme,
        onboarding_complete=False,
    )


def _add_default_categories(db: Session, user: User) -> None:
    for definition in DEFAULT_CATEGORIES:
        db.add(
            Category(
                user_id=user.id,
                stable_key=definition["key"],
                name=definition["name"],
                icon=definition["icon"],
                enabled=bool(definition["selected_by_default"] or definition["key"] == "other"),
            )
        )


def _unique_username(db: Session, preferred: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", preferred).strip("-._")[:72]
    if len(candidate) < 3:
        candidate = "budget-user"
    normalized = normalize_identity(candidate)
    if db.scalar(select(User.id).where(User.normalized_username == normalized)) is None:
        return candidate
    for suffix in range(2, 10_000):
        trial = f"{candidate[:72]}-{suffix}"
        if db.scalar(select(User.id).where(User.normalized_username == normalize_identity(trial))) is None:
            return trial
    raise ApiError(503, "username_unavailable", "A username could not be assigned")


def create_invitation(
    db: Session,
    settings: Settings,
    admin: User,
    *,
    email: str,
    base_url: str,
) -> dict[str, object]:
    _require_admin(admin)
    normalized = normalize_identity(email)
    if db.scalar(select(User.id).where(User.normalized_email == normalized)) is not None:
        raise ApiError(409, "account_exists", "A Budget account already uses that email address")

    now = utc_now()
    existing = db.scalars(
        select(UserInvitation).where(
            UserInvitation.normalized_email == normalized,
            UserInvitation.accepted_at.is_(None),
            UserInvitation.revoked_at.is_(None),
        )
    ).all()
    for item in existing:
        item.revoked_at = now

    token = secrets.token_urlsafe(32)
    invitation = UserInvitation(
        invited_by_user_id=admin.id,
        email=email,
        normalized_email=normalized,
        token_digest=_token_digest(settings, "invitation", token),
        created_at=now,
        expires_at=now + INVITATION_TTL,
        accepted_at=None,
        revoked_at=None,
    )
    db.add(invitation)
    db.flush()
    invite_url = f"{base_url.rstrip('/')}/invite?token={token}"
    delivery = "manual"
    if settings.email_configured:
        subject, body = invitation_email(invite_url)
        try:
            send_email(settings, to_email=email, subject=subject, text=body)
            delivery = "email"
        except EmailDeliveryError:
            delivery = "manual"
    return invitation_view(
        invitation,
        delivery=delivery,
        invite_url=invite_url if delivery == "manual" else None,
    )


def list_invitations(db: Session, admin: User) -> list[dict[str, object]]:
    _require_admin(admin)
    rows = db.scalars(
        select(UserInvitation)
        .where(UserInvitation.invited_by_user_id == admin.id)
        .order_by(UserInvitation.created_at.desc())
    ).all()
    return [invitation_view(row) for row in rows]


def revoke_invitation(db: Session, admin: User, invitation_id: int) -> None:
    _require_admin(admin)
    row = db.scalar(
        select(UserInvitation).where(
            UserInvitation.id == invitation_id,
            UserInvitation.invited_by_user_id == admin.id,
        )
    )
    if row is None:
        raise ApiError(404, "invitation_not_found", "The invitation was not found")
    if row.accepted_at is not None:
        raise ApiError(409, "invitation_already_accepted", "The invitation has already been accepted")
    row.revoked_at = utc_now()


def invitation_from_token(db: Session, settings: Settings, token: str) -> UserInvitation:
    row = db.scalar(
        select(UserInvitation).where(
            UserInvitation.token_digest == _token_digest(settings, "invitation", token)
        )
    )
    if row is None or not _active_invitation(row):
        raise ApiError(404, "invitation_invalid", "The invitation is invalid or has expired")
    return row


def invitation_public_view(
    db: Session, settings: Settings, token: str
) -> dict[str, object]:
    row = invitation_from_token(db, settings, token)
    return {"email": row.email, "expires_at": row.expires_at, "google_enabled": settings.google_configured}


def accept_password_invitation(
    db: Session,
    settings: Settings,
    *,
    token: str,
    username: str,
    password: str,
) -> User:
    invitation = invitation_from_token(db, settings, token)
    if db.scalar(select(User.id).where(User.normalized_email == invitation.normalized_email)) is not None:
        raise ApiError(409, "account_exists", "A Budget account already uses that email address")
    if db.scalar(
        select(User.id).where(User.normalized_username == normalize_identity(username))
    ) is not None:
        raise ApiError(409, "username_exists", "That username is already in use")
    inviter = db.scalar(
        select(User)
        .options(selectinload(User.settings))
        .where(User.id == invitation.invited_by_user_id)
    )
    now = utc_now()
    user = User(
        username=username,
        normalized_username=normalize_identity(username),
        email=invitation.email,
        normalized_email=invitation.normalized_email,
        password_hash=hash_password(password),
        is_admin=False,
        email_verified_at=now,
        last_login_at=now,
        settings=_new_user_settings(inviter),
    )
    db.add(user)
    db.flush()
    _add_default_categories(db, user)
    invitation.accepted_at = now
    db.flush()
    return user


def security_status(db: Session, settings: Settings, user: User) -> dict[str, object]:
    google = db.scalar(
        select(AuthIdentity.id).where(AuthIdentity.user_id == user.id, AuthIdentity.provider == "google")
    )
    totp = db.get(UserTotp, user.id)
    return {
        "is_admin": user.is_admin,
        "email_verified": user.email_verified_at is not None,
        "has_password": user.password_hash is not None,
        "google_enabled": settings.google_configured,
        "google_connected": google is not None,
        "two_factor_enabled": bool(totp and totp.enabled_at is not None),
        "email_delivery_configured": settings.email_configured,
        "invite_only": True,
    }


def list_sessions(db: Session, user: User, current_session_id: int) -> list[dict[str, object]]:
    rows = db.scalars(
        select(SessionRecord)
        .where(SessionRecord.user_id == user.id, SessionRecord.revoked_at.is_(None))
        .order_by(SessionRecord.last_seen_at.desc())
    ).all()
    now = utc_now()
    return [
        {
            "id": row.id,
            "current": row.id == current_session_id,
            "user_agent": row.user_agent,
            "created_at": row.created_at,
            "last_seen_at": row.last_seen_at,
            "idle_expires_at": row.idle_expires_at,
            "absolute_expires_at": row.absolute_expires_at,
        }
        for row in rows
        if row.revoked_at is None
        and as_utc(row.idle_expires_at) > now
        and as_utc(row.absolute_expires_at) > now
    ]


def revoke_named_session(db: Session, user: User, session_id: int, current_session_id: int) -> bool:
    row = db.scalar(
        select(SessionRecord).where(SessionRecord.id == session_id, SessionRecord.user_id == user.id)
    )
    if row is None:
        raise ApiError(404, "session_not_found", "The session was not found")
    if row.id == current_session_id:
        raise ApiError(409, "current_session", "Use sign out to end the current session")
    if row.revoked_at is None:
        row.revoked_at = utc_now()
        return True
    return False


def revoke_other_sessions(db: Session, user: User, current_session_id: int) -> int:
    rows = db.scalars(
        select(SessionRecord).where(
            SessionRecord.user_id == user.id,
            SessionRecord.id != current_session_id,
            SessionRecord.revoked_at.is_(None),
        )
    ).all()
    now = utc_now()
    for row in rows:
        row.revoked_at = now
    return len(rows)


def _new_password_reset(db: Session, settings: Settings, user: User) -> tuple[PasswordResetToken, str]:
    now = utc_now()
    db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    )
    token = secrets.token_urlsafe(32)
    row = PasswordResetToken(
        user_id=user.id,
        token_digest=_token_digest(settings, "password-reset", token),
        created_at=now,
        expires_at=now + PASSWORD_RESET_TTL,
        used_at=None,
    )
    db.add(row)
    db.flush()
    return row, token


def request_password_reset(
    db: Session,
    settings: Settings,
    *,
    identity: str,
    base_url: str,
) -> bool:
    normalized = normalize_identity(identity)
    user = db.scalar(
        select(User).where(
            (User.normalized_email == normalized) | (User.normalized_username == normalized)
        )
    )
    if user is None or not settings.email_configured:
        return False
    _, token = _new_password_reset(db, settings, user)
    reset_url = f"{base_url.rstrip('/')}/reset-password?token={token}"
    subject, body = password_reset_email(reset_url)
    try:
        send_email(settings, to_email=user.email, subject=subject, text=body)
        return True
    except EmailDeliveryError:
        return False


def admin_password_reset(
    db: Session,
    settings: Settings,
    admin: User,
    *,
    user_id: int,
    base_url: str,
) -> dict[str, object]:
    _require_admin(admin)
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(404, "user_not_found", "The user was not found")
    _, token = _new_password_reset(db, settings, user)
    reset_url = f"{base_url.rstrip('/')}/reset-password?token={token}"
    if settings.email_configured:
        subject, body = password_reset_email(reset_url)
        try:
            send_email(settings, to_email=user.email, subject=subject, text=body)
            return {"ok": True, "delivery": "email", "reset_url": None}
        except EmailDeliveryError:
            pass
    return {"ok": True, "delivery": "manual", "reset_url": reset_url}


def password_reset_status(db: Session, settings: Settings, token: str) -> dict[str, object]:
    row = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_digest == _token_digest(settings, "password-reset", token)
        )
    )
    if row is None or row.used_at is not None or as_utc(row.expires_at) <= utc_now():
        return {"valid": False, "email": None}
    user = db.get(User, row.user_id)
    return {"valid": user is not None, "email": user.email if user is not None else None}


def reset_password(db: Session, settings: Settings, *, token: str, password: str) -> User:
    row = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_digest == _token_digest(settings, "password-reset", token))
        .with_for_update()
    )
    now = utc_now()
    if row is None or row.used_at is not None or as_utc(row.expires_at) <= now:
        raise ApiError(400, "password_reset_invalid", "The password reset link is invalid or has expired")
    user = db.get(User, row.user_id)
    if user is None:
        raise ApiError(400, "password_reset_invalid", "The password reset link is invalid or has expired")
    user.password_hash = hash_password(password)
    user.email_verified_at = user.email_verified_at or now
    row.used_at = now
    revoke_user_sessions(db, user.id)
    return user


def _encryption_key(settings: Settings) -> SecretStr:
    return SecretStr(settings.secret_value("encryption_key"))


def _totp_row(db: Session, user_id: int) -> UserTotp | None:
    return db.get(UserTotp, user_id)


def begin_totp_setup(db: Session, settings: Settings, user: User) -> dict[str, str]:
    secret = new_totp_secret()
    ciphertext, nonce = encrypt_user_secret(
        secret,
        _encryption_key(settings),
        user_id=user.id,
        purpose="totp",
    )
    row = _totp_row(db, user.id)
    now = utc_now()
    if row is None:
        row = UserTotp(
            user_id=user.id,
            secret_ciphertext=ciphertext,
            secret_nonce=nonce,
            recovery_codes_json="[]",
            created_at=now,
            enabled_at=None,
        )
        db.add(row)
    else:
        row.secret_ciphertext = ciphertext
        row.secret_nonce = nonce
        row.recovery_codes_json = "[]"
        row.created_at = now
        row.enabled_at = None
    db.flush()
    return {"secret": secret, "otpauth_uri": otpauth_uri(secret, email=user.email)}


def _totp_secret(settings: Settings, row: UserTotp) -> str:
    return decrypt_user_secret(
        row.secret_ciphertext,
        row.secret_nonce,
        _encryption_key(settings),
        user_id=row.user_id,
        purpose="totp",
    )


def _recovery_digest(settings: Settings, user_id: int, code: str) -> str:
    normalized = code.strip().replace("-", "").replace(" ", "").upper()
    return private_identifier(settings, f"totp-recovery:{user_id}", normalized)


def confirm_totp(db: Session, settings: Settings, user: User, code: str) -> list[str]:
    row = _totp_row(db, user.id)
    if row is None:
        raise ApiError(409, "totp_setup_required", "Start two-factor setup first")
    if not verify_totp(_totp_secret(settings, row), code):
        raise ApiError(400, "totp_invalid", "The verification code is incorrect")
    recovery_codes = [secrets.token_hex(5).upper() for _ in range(RECOVERY_CODE_COUNT)]
    row.recovery_codes_json = json.dumps(
        [_recovery_digest(settings, user.id, item) for item in recovery_codes], separators=(",", ":")
    )
    row.enabled_at = utc_now()
    db.flush()
    return recovery_codes


def verify_second_factor(
    db: Session,
    settings: Settings,
    user: User,
    code: str,
    *,
    consume_recovery: bool = True,
) -> bool:
    row = _totp_row(db, user.id)
    if row is None or row.enabled_at is None:
        return False
    if verify_totp(_totp_secret(settings, row), code):
        return True
    try:
        stored = cast(list[str], json.loads(row.recovery_codes_json))
    except (json.JSONDecodeError, TypeError):
        stored = []
    digest = _recovery_digest(settings, user.id, code)
    if digest not in stored:
        return False
    if consume_recovery:
        stored.remove(digest)
        row.recovery_codes_json = json.dumps(stored, separators=(",", ":"))
    return True


def disable_totp(db: Session, settings: Settings, user: User, code: str) -> None:
    row = _totp_row(db, user.id)
    if row is None or row.enabled_at is None:
        raise ApiError(409, "totp_not_enabled", "Two-factor authentication is not enabled")
    if not verify_second_factor(db, settings, user, code):
        raise ApiError(400, "totp_invalid", "The verification code is incorrect")
    db.delete(row)


def totp_enabled(db: Session, user_id: int) -> bool:
    row = _totp_row(db, user_id)
    return bool(row and row.enabled_at is not None)


def create_two_factor_challenge(db: Session, settings: Settings, user: User) -> str:
    db.execute(delete(TwoFactorChallenge).where(TwoFactorChallenge.user_id == user.id))
    token = secrets.token_urlsafe(32)
    now = utc_now()
    db.add(
        TwoFactorChallenge(
            token_digest=_token_digest(settings, "two-factor-challenge", token),
            user_id=user.id,
            attempts=0,
            created_at=now,
            expires_at=now + TWO_FACTOR_CHALLENGE_TTL,
            consumed_at=None,
        )
    )
    db.flush()
    return token


def consume_two_factor_challenge(
    db: Session,
    settings: Settings,
    *,
    token: str,
    code: str,
) -> User:
    row = db.scalar(
        select(TwoFactorChallenge)
        .where(
            TwoFactorChallenge.token_digest
            == _token_digest(settings, "two-factor-challenge", token)
        )
        .with_for_update()
    )
    now = utc_now()
    if (
        row is None
        or row.consumed_at is not None
        or as_utc(row.expires_at) <= now
        or row.attempts >= 5
    ):
        raise ApiError(401, "two_factor_invalid", "The two-factor challenge is invalid or expired")
    user = db.scalar(
        select(User).options(selectinload(User.settings)).where(User.id == row.user_id)
    )
    if user is None:
        raise ApiError(401, "two_factor_invalid", "The two-factor challenge is invalid or expired")
    if not verify_second_factor(db, settings, user, code):
        row.attempts += 1
        if row.attempts >= 5:
            row.consumed_at = now
        raise ApiError(401, "two_factor_invalid", "The verification code is incorrect")
    row.consumed_at = now
    return user


def _safe_return_to(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//") and len(value) <= 500:
        return value
    return "/dashboard"


def begin_google_flow(
    db: Session,
    settings: Settings,
    *,
    purpose: str,
    user: User | None,
    invitation_token: str | None,
    return_to: str | None,
) -> str:
    if not settings.google_configured:
        raise ApiError(404, "google_not_configured", "Google sign-in is not configured")
    if purpose not in {"login", "link"}:
        raise ApiError(400, "google_flow_invalid", "The Google sign-in request is invalid")
    if purpose == "link" and user is None:
        raise ApiError(401, "authentication_required", "Authentication is required")

    invitation: UserInvitation | None = None
    if invitation_token:
        invitation = invitation_from_token(db, settings, invitation_token)

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    now = utc_now()
    db.add(
        OAuthState(
            state_digest=_token_digest(settings, "google-oauth-state", state),
            nonce_digest=_token_digest(settings, "google-oauth-nonce", nonce),
            purpose=purpose,
            user_id=user.id if user is not None else None,
            invitation_id=invitation.id if invitation is not None else None,
            return_to=_safe_return_to(return_to),
            created_at=now,
            expires_at=now + OAUTH_STATE_TTL,
        )
    )
    db.flush()
    login_hint = invitation.email if invitation is not None else user.email if user is not None else None
    return authorization_url(settings, state=state, nonce=nonce, login_hint=login_hint)


def oauth_state(db: Session, settings: Settings, state: str) -> OAuthState:
    row = db.scalar(
        select(OAuthState)
        .where(OAuthState.state_digest == _token_digest(settings, "google-oauth-state", state))
        .with_for_update()
    )
    if row is None or as_utc(row.expires_at) <= utc_now():
        raise ApiError(400, "google_state_invalid", "The Google sign-in request expired or could not be verified")
    return row


def complete_google_flow(
    db: Session,
    settings: Settings,
    *,
    state_row: OAuthState,
    identity: GoogleIdentity,
) -> tuple[User, str]:
    if _token_digest(settings, "google-oauth-nonce", identity.nonce) != state_row.nonce_digest:
        raise ApiError(400, "google_nonce_invalid", "The Google sign-in response could not be verified")
    normalized_email = normalize_identity(identity.email)
    existing_identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "google", AuthIdentity.subject == identity.subject
        )
    )

    if state_row.purpose == "link":
        if state_row.user_id is None:
            raise ApiError(400, "google_state_invalid", "The Google sign-in request is invalid")
        user = db.scalar(
            select(User).options(selectinload(User.settings)).where(User.id == state_row.user_id)
        )
        if user is None:
            raise ApiError(404, "user_not_found", "The user was not found")
        if existing_identity is not None and existing_identity.user_id != user.id:
            raise ApiError(409, "google_already_linked", "That Google account is linked to another Budget user")
        current = db.scalar(
            select(AuthIdentity).where(AuthIdentity.user_id == user.id, AuthIdentity.provider == "google")
        )
        if current is None:
            db.add(
                AuthIdentity(
                    user_id=user.id,
                    provider="google",
                    subject=identity.subject,
                    email=identity.email,
                    created_at=utc_now(),
                )
            )
        elif current.subject != identity.subject:
            raise ApiError(409, "google_already_linked", "A different Google account is already connected")
        else:
            current.email = identity.email
        user.email_verified_at = user.email_verified_at or utc_now()
        db.delete(state_row)
        db.flush()
        return user, state_row.return_to

    if existing_identity is not None:
        user = db.scalar(
            select(User).options(selectinload(User.settings)).where(User.id == existing_identity.user_id)
        )
        if user is None:
            raise ApiError(401, "google_identity_invalid", "The Google account could not be signed in")
        existing_identity.email = identity.email
        user.email_verified_at = user.email_verified_at or utc_now()
        db.delete(state_row)
        db.flush()
        return user, state_row.return_to

    existing_user = db.scalar(
        select(User).options(selectinload(User.settings)).where(User.normalized_email == normalized_email)
    )
    if existing_user is not None:
        raise ApiError(
            409,
            "google_link_required",
            "A Budget account already uses this email. Sign in with your password and connect Google from Settings.",
        )

    invitation = db.get(UserInvitation, state_row.invitation_id) if state_row.invitation_id else None
    if invitation is None or not _active_invitation(invitation):
        raise ApiError(403, "invitation_required", "A valid Budget invitation is required to create an account")
    if invitation.normalized_email != normalized_email:
        raise ApiError(403, "invitation_email_mismatch", "Use the Google account that received the Budget invitation")

    inviter = db.scalar(
        select(User).options(selectinload(User.settings)).where(User.id == invitation.invited_by_user_id)
    )
    preferred = identity.email.split("@", 1)[0]
    if identity.name:
        preferred = identity.name.replace(" ", ".")
    username = _unique_username(db, preferred)
    now = utc_now()
    user = User(
        username=username,
        normalized_username=normalize_identity(username),
        email=identity.email,
        normalized_email=normalized_email,
        password_hash=None,
        is_admin=False,
        email_verified_at=now,
        last_login_at=now,
        settings=_new_user_settings(inviter),
    )
    db.add(user)
    db.flush()
    _add_default_categories(db, user)
    db.add(
        AuthIdentity(
            user_id=user.id,
            provider="google",
            subject=identity.subject,
            email=identity.email,
            created_at=now,
        )
    )
    invitation.accepted_at = now
    db.delete(state_row)
    db.flush()
    return user, state_row.return_to


def unlink_google(db: Session, user: User) -> None:
    row = db.scalar(
        select(AuthIdentity).where(AuthIdentity.user_id == user.id, AuthIdentity.provider == "google")
    )
    if row is None:
        raise ApiError(404, "google_not_linked", "Google is not connected to this account")
    if user.password_hash is None:
        raise ApiError(409, "password_required", "Set a password before disconnecting your only sign-in method")
    db.delete(row)


def admin_users(db: Session, admin: User) -> list[dict[str, object]]:
    _require_admin(admin)
    users = db.scalars(select(User).order_by(User.created_at)).all()
    google_user_ids = set(
        db.scalars(select(AuthIdentity.user_id).where(AuthIdentity.provider == "google")).all()
    )
    return [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "email_verified": user.email_verified_at is not None,
            "is_admin": user.is_admin,
            "has_password": user.password_hash is not None,
            "google_connected": user.id in google_user_ids,
            "last_login_at": user.last_login_at,
        }
        for user in users
    ]


def verify_account_delete_password(user: User, password: str | None) -> None:
    if user.password_hash is None:
        return
    if not password:
        raise ApiError(400, "password_required", "Enter your current password to delete the account")
    valid, _ = verify_password(user.password_hash, password)
    if not valid:
        raise ApiError(403, "invalid_credentials", "The password is incorrect")


def can_delete_admin(db: Session, user: User) -> None:
    if not user.is_admin:
        return
    other_users = int(db.scalar(select(func.count(User.id)).where(User.id != user.id)) or 0)
    other_admins = int(
        db.scalar(select(func.count(User.id)).where(User.id != user.id, User.is_admin.is_(True))) or 0
    )
    if other_users and not other_admins:
        raise ApiError(
            409,
            "last_admin",
            "This is the only administrator account. Remove other users before deleting it.",
        )
