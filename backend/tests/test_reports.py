from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import FinancialSnapshot, RecurringStream, User
from app.services.reports import capture_snapshot
from tests.conftest import csrf_headers


def _account(client: TestClient, csrf: str, balance: str) -> int:
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
    return int(response.json()["id"])


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


def test_spending_and_budget_analytics(authenticated, database) -> None:
    client, csrf = authenticated
    account_id = _account(client, csrf, "5000.0000")
    categories_response = client.get("/api/v1/categories/selection")
    assert categories_response.status_code == 200
    categories = {item["key"]: item["id"] for item in categories_response.json()["categories"]}
    today = datetime.now(ZoneInfo("America/Chicago")).date()

    annual = client.put(
        f"/api/v1/budget/years/{today.year}/plan",
        headers=csrf_headers(csrf),
        json={
            "planned_income": "60000.0000",
            "notes": None,
            "categories": [
                {"category_id": categories["groceries"], "annual_amount": "6000.0000", "distribution": "even", "monthly_amount": None, "custom_months": [], "rollover_mode": "off"},
                {"category_id": categories["restaurants"], "annual_amount": "2400.0000", "distribution": "even", "monthly_amount": None, "custom_months": [], "rollover_mode": "off"},
            ],
        },
    )
    assert annual.status_code == 200, annual.text

    def transaction(days_ago: int, merchant: str, amount: str, kind: str, category_key: str) -> None:
        response = client.post(
            "/api/v1/transactions",
            headers=csrf_headers(csrf),
            json={
                "account_id": account_id,
                "category_id": categories[category_key],
                "posted_date": (today - timedelta(days=days_ago)).isoformat(),
                "authorized_date": None,
                "merchant": merchant,
                "description": merchant,
                "amount": amount,
                "kind": kind,
                "pending": False,
                "notes": None,
            },
        )
        assert response.status_code == 201, response.text

    transaction(2, "Payroll", "2500.0000", "income", "income")
    transaction(3, "Fresh Market", "-320.0000", "expense", "groceries")
    transaction(4, "Dinner House", "-180.0000", "expense", "restaurants")
    transaction(5, "Netflix", "-20.0000", "expense", "restaurants")
    transaction(35, "Dinner House", "-100.0000", "expense", "restaurants")

    with database.session_factory() as db:
        user = db.scalar(select(User).where(User.normalized_username == "owner"))
        assert user is not None
        db.add(
            RecurringStream(
                user_id=user.id, account_id=account_id, merchant_key="netflix", display_name="Netflix",
                kind="expense", cadence="monthly", average_amount=Decimal("20"), last_amount=Decimal("20"),
                last_date=today - timedelta(days=5), next_expected_date=today + timedelta(days=25),
                occurrence_count=3, active=True,
            )
        )
        db.commit()

    spending = client.get("/api/v1/reports/spending?range=30d")
    assert spending.status_code == 200, spending.text
    body = spending.json()
    assert body["range"]["key"] == "30d"
    assert body["summary"]["income"] == "2500.0000"
    assert body["summary"]["spending"] == "520.0000"
    assert body["summary"]["spending_change_amount"] == "420.0000"
    assert body["recurring"]["recurring"] == "20.0000"
    grocery = next(item for item in body["categories"] if item["key"] == "groceries")
    assert grocery["amount"] == "320.0000"
    assert any(item["name"] == "Fresh Market" for item in body["top_merchants"])

    budget = client.get("/api/v1/reports/budget?range=3m")
    assert budget.status_code == 200, budget.text
    budget_body = budget.json()
    assert budget_body["year"] == today.year
    assert budget_body["has_annual_plan"] is True
    assert Decimal(budget_body["summary"]["spent"]) >= Decimal("520")
    assert any(item["name"] == "Groceries" for item in budget_body["categories"])
    assert 1 <= len(budget_body["months"]) <= 3


def test_report_range_validation(authenticated) -> None:
    client, _ = authenticated
    assert client.get("/api/v1/reports/spending?range=wat").status_code == 422
    assert client.get("/api/v1/reports/budget?range=wat").status_code == 422
