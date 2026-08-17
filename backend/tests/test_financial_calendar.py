from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import Account, Debt, RecurringStream, User
from tests.conftest import csrf_headers


def _account(client, csrf: str, *, name: str = "Checking", balance: str = "2200.0000") -> int:
    response = client.post(
        "/api/v1/accounts",
        headers=csrf_headers(csrf),
        json={
            "name": name,
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
    return int(response.json()["id"])


def test_financial_calendar_projects_recurring_and_debt_without_inventing_observed_events(authenticated, database) -> None:
    client, csrf = authenticated
    account_id = _account(client, csrf)
    today = datetime.now(ZoneInfo("America/Chicago")).date()

    with database.session_factory() as db:
        user = db.scalar(select(User).where(User.normalized_username == "owner"))
        account = db.scalar(select(Account).where(Account.id == account_id))
        assert user is not None and account is not None
        db.add_all(
            [
                RecurringStream(
                    user_id=user.id,
                    account_id=account_id,
                    merchant_key="northstar software",
                    display_name="Northstar Software",
                    kind="income",
                    cadence="biweekly",
                    average_amount=Decimal("1500.0000"),
                    last_amount=Decimal("1500.0000"),
                    last_date=today - timedelta(days=14),
                    next_expected_date=today + timedelta(days=2),
                    occurrence_count=5,
                    price_change_pct=Decimal("0"),
                    active=True,
                ),
                RecurringStream(
                    user_id=user.id,
                    account_id=account_id,
                    merchant_key="streambox",
                    display_name="StreamBox",
                    kind="expense",
                    cadence="monthly",
                    average_amount=Decimal("24.9900"),
                    last_amount=Decimal("24.9900"),
                    last_date=today - timedelta(days=30),
                    next_expected_date=today + timedelta(days=4),
                    occurrence_count=4,
                    price_change_pct=Decimal("6.5"),
                    active=True,
                ),
                Debt(
                    user_id=user.id,
                    linked_account_id=None,
                    name="Auto loan",
                    debt_type="auto",
                    balance=Decimal("8000.0000"),
                    apr=Decimal("5.0000"),
                    minimum_payment=Decimal("300.0000"),
                    extra_payment=Decimal("0"),
                    strategy_priority=100,
                    due_day=min(today.day + 5, 28),
                    active=True,
                    notes=None,
                ),
            ]
        )
        db.commit()

    response = client.get(f"/api/v1/financial-calendar?month={today:%Y-%m}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"]["projection_available"] is True
    assert body["summary"]["cash_available_now"] == "2200.0000"
    assert body["recurring"]["detected_streams"] == 2
    assert any(row["name"] == "Northstar Software" and row["status"] == "expected" for row in body["events"])
    assert any(row["name"] == "StreamBox" and row["status"] == "expected" for row in body["events"])
    assert any(row["name"] == "Auto loan" and row["status"] == "planned" for row in body["events"])
    assert body["projection"]
    assert all(row["status"] != "observed" for row in body["events"])


def test_financial_calendar_rejects_bad_month(authenticated) -> None:
    client, _ = authenticated
    assert client.get("/api/v1/financial-calendar?month=2026-99").status_code == 422
