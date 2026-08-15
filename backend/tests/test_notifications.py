from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.database import Database
from app.models import FinancialGoal, InsightRecord, Notification, User
from app.services.notifications import scan_user_notifications
from tests.conftest import csrf_headers


def test_notification_preferences_and_inbox_are_owner_scoped(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    headers = csrf_headers(csrf)

    defaults = client.get("/api/v1/notifications/preferences")
    assert defaults.status_code == 200, defaults.text
    assert defaults.json()["spending_alerts"] is True
    assert defaults.json()["email_enabled"] is False

    updated = client.patch(
        "/api/v1/notifications/preferences",
        headers=headers,
        json={"large_transaction_alerts": True, "large_transaction_threshold": "425.0000"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["large_transaction_alerts"] is True
    assert updated.json()["large_transaction_threshold"] == "425.0000"

    with database.session_factory() as db:
        user = db.scalar(select(User))
        assert user is not None
        row = Notification(
            user_id=user.id,
            fingerprint="test:one",
            notification_type="test",
            severity="important",
            title="Test notification",
            body="Test body",
            action_route="/dashboard",
            data_json="{}",
            occurred_at=datetime.now(UTC),
        )
        db.add(row)
        db.commit()
        notification_id = row.id

    inbox = client.get("/api/v1/notifications?status=unread")
    assert inbox.status_code == 200, inbox.text
    assert inbox.json()["unread_count"] == 1
    assert inbox.json()["notifications"][0]["id"] == notification_id

    marked = client.patch(
        f"/api/v1/notifications/{notification_id}", headers=headers, json={"read": True}
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["read_at"] is not None
    assert client.get("/api/v1/notifications/unread-count").json()["unread_count"] == 0


def test_notification_scan_dedupes_insight_and_highest_goal_milestone(
    authenticated: tuple[TestClient, str], database: Database, settings: Settings, monkeypatch
) -> None:
    client, _ = authenticated
    del client
    with database.session_factory() as db:
        user = db.scalar(select(User).options(selectinload(User.settings)))
        assert user is not None
        now = datetime.now(UTC)
        db.add(
            InsightRecord(
                user_id=user.id,
                fingerprint="spending-fingerprint",
                signal_type="negative_safe_to_spend",
                category="cash_flow",
                priority="critical",
                score=98,
                status="active",
                title="Safe to spend is below zero",
                summary="Budget calculates a negative safe-to-spend amount.",
                recommendation="Reduce discretionary spending.",
                evidence_json=json.dumps([]),
                action_route="/budget",
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        db.add(
            FinancialGoal(
                user_id=user.id,
                name="Emergency Fund",
                goal_type="emergency_fund",
                target_amount=Decimal("1000.0000"),
                current_amount=Decimal("620.0000"),
                monthly_contribution=Decimal("50.0000"),
                priority=1,
                active=True,
            )
        )
        db.commit()

        monkeypatch.setattr("app.services.notifications.refresh_insights", lambda _db, _user: None)
        first = scan_user_notifications(db, settings, user)
        second = scan_user_notifications(db, settings, user)
        assert first["created"] == 2
        assert second["created"] == 0
        rows = list(db.scalars(select(Notification).where(Notification.user_id == user.id)).all())
        assert len(rows) == 2
        assert {row.notification_type for row in rows} == {"negative_safe_to_spend", "goal_milestone"}
        milestone = next(row for row in rows if row.notification_type == "goal_milestone")
        assert json.loads(milestone.data_json)["milestone"] == 50


def test_read_all_marks_only_current_users_notifications(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    with database.session_factory() as db:
        owner = db.scalar(select(User))
        assert owner is not None
        other = User(
            username="other",
            normalized_username="other",
            email="other@example.com",
            normalized_email="other@example.com",
            password_hash=None,
            is_admin=False,
        )
        db.add(other)
        db.flush()
        now = datetime.now(UTC)
        db.add_all([
            Notification(user_id=owner.id, fingerprint="owner:n", notification_type="test", severity="info", title="Owner", body="Owner", data_json="{}", occurred_at=now),
            Notification(user_id=other.id, fingerprint="other:n", notification_type="test", severity="info", title="Other", body="Other", data_json="{}", occurred_at=now),
        ])
        db.commit()
    response = client.post("/api/v1/notifications/read-all", headers=csrf_headers(csrf))
    assert response.status_code == 200, response.text
    with database.session_factory() as db:
        owner_unread = int(db.scalar(select(func.count(Notification.id)).where(Notification.fingerprint == "owner:n", Notification.read_at.is_(None))) or 0)
        other_unread = int(db.scalar(select(func.count(Notification.id)).where(Notification.fingerprint == "other:n", Notification.read_at.is_(None))) or 0)
        assert owner_unread == 0
        assert other_unread == 1
