from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    AuditEvent,
    LoginThrottle,
    OAuthState,
    PasswordResetToken,
    ReportExport,
    SessionRecord,
    TwoFactorChallenge,
    User,
    UserInvitation,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _rowcount(result: object) -> int:
    value = getattr(result, "rowcount", 0)
    return int(value or 0)


def _prune_report_exports(db: Session, settings: Settings, now: datetime) -> tuple[int, int]:
    age_cutoff = now - timedelta(days=settings.maintenance_export_retention_days)
    deleted_by_age = _rowcount(
        db.execute(delete(ReportExport).where(ReportExport.created_at < age_cutoff))
    )

    deleted_by_cap = 0
    user_ids = list(db.scalars(select(User.id)).all())
    for user_id in user_ids:
        stale_ids = list(
            db.scalars(
                select(ReportExport.id)
                .where(ReportExport.user_id == user_id)
                .order_by(ReportExport.created_at.desc(), ReportExport.id.desc())
                .offset(settings.maintenance_export_max_per_user)
            ).all()
        )
        if stale_ids:
            deleted_by_cap += _rowcount(
                db.execute(delete(ReportExport).where(ReportExport.id.in_(stale_ids)))
            )
    return deleted_by_age, deleted_by_cap


def run_maintenance(
    db: Session, settings: Settings, *, now: datetime | None = None
) -> dict[str, int]:
    """Prune bounded operational history without touching financial source records.

    Stage 6 deliberately avoids deleting transactions, budgets, goals, snapshots,
    notifications, or Advisor history. It only removes expired authentication
    artifacts, old audit history, and reproducible report-export blobs.
    """

    current = now or _utc_now()
    auth_cutoff = current - timedelta(days=settings.maintenance_auth_retention_days)
    audit_cutoff = current - timedelta(days=settings.maintenance_audit_retention_days)

    sessions = _rowcount(
        db.execute(
            delete(SessionRecord).where(
                or_(
                    SessionRecord.absolute_expires_at < auth_cutoff,
                    SessionRecord.idle_expires_at < auth_cutoff,
                    SessionRecord.revoked_at < auth_cutoff,
                )
            )
        )
    )
    invitations = _rowcount(
        db.execute(delete(UserInvitation).where(UserInvitation.expires_at < auth_cutoff))
    )
    password_resets = _rowcount(
        db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < auth_cutoff))
    )
    oauth_states = _rowcount(
        db.execute(delete(OAuthState).where(OAuthState.expires_at < auth_cutoff))
    )
    two_factor_challenges = _rowcount(
        db.execute(delete(TwoFactorChallenge).where(TwoFactorChallenge.expires_at < auth_cutoff))
    )
    login_throttles = _rowcount(
        db.execute(
            delete(LoginThrottle).where(
                LoginThrottle.updated_at < auth_cutoff,
                or_(LoginThrottle.blocked_until.is_(None), LoginThrottle.blocked_until < current),
            )
        )
    )
    audit_events = _rowcount(
        db.execute(delete(AuditEvent).where(AuditEvent.created_at < audit_cutoff))
    )
    exports_by_age, exports_by_cap = _prune_report_exports(db, settings, current)

    db.commit()
    return {
        "sessions_deleted": sessions,
        "invitations_deleted": invitations,
        "password_resets_deleted": password_resets,
        "oauth_states_deleted": oauth_states,
        "two_factor_challenges_deleted": two_factor_challenges,
        "login_throttles_deleted": login_throttles,
        "audit_events_deleted": audit_events,
        "report_exports_deleted": exports_by_age + exports_by_cap,
        "report_exports_deleted_by_age": exports_by_age,
        "report_exports_deleted_by_cap": exports_by_cap,
    }


def maintenance_storage_status(db: Session, settings: Settings) -> dict[str, int]:
    export_count = int(db.scalar(select(func.count(ReportExport.id))) or 0)
    export_bytes = int(db.scalar(select(func.coalesce(func.sum(ReportExport.file_size), 0))) or 0)
    return {
        "report_export_count": export_count,
        "report_export_bytes": export_bytes,
        "export_retention_days": settings.maintenance_export_retention_days,
        "export_max_per_user": settings.maintenance_export_max_per_user,
        "auth_retention_days": settings.maintenance_auth_retention_days,
        "audit_retention_days": settings.maintenance_audit_retention_days,
        "minimum_free_bytes": settings.maintenance_min_free_gb * 1024 * 1024 * 1024,
    }
