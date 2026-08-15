from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.security import utc_now
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
from app.services.maintenance import maintenance_storage_status, run_maintenance


def test_maintenance_prunes_only_bounded_operational_history(
    authenticated, database, settings
) -> None:
    _client, _csrf = authenticated
    now = utc_now()
    policy: Settings = settings.model_copy(
        update={
            "maintenance_auth_retention_days": 7,
            "maintenance_audit_retention_days": 30,
            "maintenance_export_retention_days": 30,
            "maintenance_export_max_per_user": 2,
        }
    )

    with database.session_factory() as db:
        user = db.scalar(select(User))
        assert user is not None

        db.add_all(
            [
                SessionRecord(
                    user_id=user.id,
                    token_digest="old-session-token",
                    csrf_digest="old-session-csrf",
                    created_at=now - timedelta(days=40),
                    last_seen_at=now - timedelta(days=40),
                    idle_expires_at=now - timedelta(days=20),
                    absolute_expires_at=now - timedelta(days=20),
                    revoked_at=None,
                    client_key=None,
                    user_agent=None,
                ),
                UserInvitation(
                    invited_by_user_id=user.id,
                    email="old@example.test",
                    normalized_email="old@example.test",
                    token_digest="old-invite-token",
                    expires_at=now - timedelta(days=20),
                    accepted_at=None,
                    revoked_at=None,
                    created_at=now - timedelta(days=30),
                ),
                PasswordResetToken(
                    user_id=user.id,
                    token_digest="old-reset-token",
                    expires_at=now - timedelta(days=20),
                    used_at=None,
                    created_at=now - timedelta(days=21),
                ),
                OAuthState(
                    state_digest="old-oauth-state",
                    nonce_digest="old-oauth-nonce",
                    purpose="login",
                    user_id=None,
                    invitation_id=None,
                    return_to="/",
                    created_at=now - timedelta(days=20),
                    expires_at=now - timedelta(days=20),
                ),
                TwoFactorChallenge(
                    token_digest="old-2fa-token",
                    user_id=user.id,
                    attempts=0,
                    created_at=now - timedelta(days=20),
                    expires_at=now - timedelta(days=20),
                    consumed_at=None,
                ),
                LoginThrottle(
                    key="old-login-throttle",
                    failed_attempts=4,
                    window_started_at=now - timedelta(days=20),
                    blocked_until=now - timedelta(days=19),
                    updated_at=now - timedelta(days=20),
                ),
                AuditEvent(
                    user_id=user.id,
                    subject_key="maintenance-test",
                    action="old.event",
                    outcome="success",
                    request_id=None,
                    detail=None,
                    created_at=now - timedelta(days=60),
                ),
            ]
        )
        # Old-by-age export plus three recent exports: the newest two should survive the cap.
        for index, age_days in enumerate((45, 3, 2, 1), start=1):
            content = f"export-{index}".encode()
            db.add(
                ReportExport(
                    user_id=user.id,
                    saved_report_id=None,
                    name=f"Export {index}",
                    format="csv",
                    range_key="30d",
                    sections_json='["overview"]',
                    payload_json="{}",
                    content_blob=content,
                    content_sha256=("a" * 64),
                    file_size=len(content),
                    created_at=now - timedelta(days=age_days),
                )
            )
        db.commit()

        result = run_maintenance(db, policy, now=now)
        assert result["sessions_deleted"] == 1
        assert result["invitations_deleted"] == 1
        assert result["password_resets_deleted"] == 1
        assert result["oauth_states_deleted"] == 1
        assert result["two_factor_challenges_deleted"] == 1
        assert result["login_throttles_deleted"] == 1
        assert result["audit_events_deleted"] == 1
        assert result["report_exports_deleted_by_age"] == 1
        assert result["report_exports_deleted_by_cap"] == 1
        assert result["report_exports_deleted"] == 2

        exports = list(
            db.scalars(
                select(ReportExport)
                .where(ReportExport.user_id == user.id)
                .order_by(ReportExport.created_at.desc())
            ).all()
        )
        assert [row.name for row in exports] == ["Export 4", "Export 3"]
        old_audit_count = db.scalar(
            select(func.count(AuditEvent.id)).where(AuditEvent.action == "old.event")
        )
        assert old_audit_count == 0

        storage = maintenance_storage_status(db, policy)
        assert storage["report_export_count"] == 2
        assert storage["report_export_bytes"] == sum(row.file_size for row in exports)
        assert storage["export_max_per_user"] == 2
        assert storage["minimum_free_bytes"] == policy.maintenance_min_free_gb * 1024**3
