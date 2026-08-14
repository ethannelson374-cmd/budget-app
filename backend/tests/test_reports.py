from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import FinancialSnapshot, User
from app.services.reports import capture_snapshot
from tests.conftest import csrf_headers


def _account(client: TestClient, csrf: str, balance: str) -> None:
    response = client.post(
        "/api/v1/accounts",
        headers=csrf_headers(csrf),
        json={
            "name": "Checking",
            "official_name": None,
            "account_type": "depository",
            "account_subtype": "checking",
            "current_balance": balance,
            "available_balance": balance,
            "credit_limit": None,
            "currency": "USD",
            "mask_last4": None,
        },
    )
    assert response.status_code == 201, response.text


def test_reports_overview_and_daily_snapshot_upsert(authenticated, database) -> None:
    client, csrf = authenticated
    _account(client, csrf, "2500.0000")

    overview = client.get("/api/v1/reports/overview?days=90")
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["currency"] == "USD"
    assert body["current"]["cash_available"] == "2500.0000"
    assert body["history"] == []

    with database.session_factory() as db:
        user = db.scalar(select(User).where(User.normalized_username == "owner"))
        assert user is not None
        capture_snapshot(db, user)
        db.commit()
        first = db.scalar(select(FinancialSnapshot).where(FinancialSnapshot.user_id == user.id))
        assert first is not None
        assert first.cash_available == Decimal("2500.0000")

        first.cash_available = Decimal("1")
        db.flush()
        capture_snapshot(db, user)
        db.commit()
        count = db.scalar(
            select(func.count())
            .select_from(FinancialSnapshot)
            .where(FinancialSnapshot.user_id == user.id)
        )
        assert count == 1

    overview = client.get("/api/v1/reports/overview?days=90")
    assert overview.status_code == 200, overview.text
    assert len(overview.json()["history"]) == 1
    assert overview.json()["history"][0]["cash_available"] == "2500.0000"


def test_reports_days_validation(authenticated) -> None:
    client, _ = authenticated
    assert client.get("/api/v1/reports/overview?days=0").status_code == 422
    assert client.get("/api/v1/reports/overview?days=3661").status_code == 422
