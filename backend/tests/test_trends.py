from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import AccountBalanceSnapshot, FinancialSnapshot, User
from app.services.reports import capture_snapshot
from tests.conftest import csrf_headers


def _account(client, csrf: str, *, name: str, balance: str, account_type: str = "depository") -> int:
    response = client.post(
        "/api/v1/accounts",
        headers=csrf_headers(csrf),
        json={
            "name": name,
            "official_name": None,
            "account_type": account_type,
            "account_subtype": "checking" if account_type == "depository" else "credit card",
            "current_balance": balance,
            "available_balance": balance if account_type == "depository" else None,
            "credit_limit": "5000.0000" if account_type == "credit" else None,
            "currency": "USD",
            "mask_last4": None,
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _transaction(client, csrf: str, *, account_id: int, category_id: int, when, label: str, amount: str, kind: str) -> None:
    response = client.post(
        "/api/v1/transactions",
        headers=csrf_headers(csrf),
        json={
            "account_id": account_id,
            "category_id": category_id,
            "posted_date": when.isoformat(),
            "authorized_date": None,
            "merchant": label,
            "description": label,
            "amount": amount,
            "kind": kind,
            "pending": False,
            "notes": None,
        },
    )
    assert response.status_code == 201, response.text


def _financial_snapshot(user_id: int, snapshot_date, net_worth: str, cash: str) -> FinancialSnapshot:
    return FinancialSnapshot(
        user_id=user_id,
        snapshot_date=snapshot_date,
        currency="USD",
        net_worth=Decimal(net_worth),
        cash_available=Decimal(cash),
        planned_income=Decimal("5000"),
        actual_income=Decimal("3000"),
        budgeted=Decimal("2000"),
        spent=Decimal("500"),
        safe_to_spend=Decimal("2000"),
        planning_commitments=Decimal("0"),
        goal_reserves=Decimal("0"),
        total_goal_target=Decimal("0"),
        total_goal_current=Decimal("0"),
        monthly_goal_contributions=Decimal("0"),
        total_debt=Decimal("1000"),
        planned_monthly_debt_payment=Decimal("0"),
        reserve_balance=Decimal("0"),
        projected_30_day=Decimal(cash),
        projected_60_day=Decimal(cash),
        projected_90_day=Decimal(cash),
        planned_debt_free_date=None,
    )


def test_trends_combines_snapshots_accounts_and_transaction_momentum(authenticated, database) -> None:
    client, csrf = authenticated
    checking_id = _account(client, csrf, name="Checking", balance="5000.0000")
    credit_id = _account(client, csrf, name="Rewards Card", balance="-1000.0000", account_type="credit")
    categories = {row["key"]: row["id"] for row in client.get("/api/v1/categories/selection").json()["categories"]}
    today = datetime.now(ZoneInfo("America/Chicago")).date()

    _transaction(client, csrf, account_id=checking_id, category_id=categories["income"], when=today - timedelta(days=2), label="Payroll", amount="3000.0000", kind="income")
    _transaction(client, csrf, account_id=checking_id, category_id=categories["groceries"], when=today - timedelta(days=1), label="Fresh Market", amount="-500.0000", kind="expense")
    _transaction(client, csrf, account_id=checking_id, category_id=categories["income"], when=today - timedelta(days=32), label="Payroll", amount="2500.0000", kind="income")
    _transaction(client, csrf, account_id=checking_id, category_id=categories["groceries"], when=today - timedelta(days=33), label="Fresh Market", amount="-400.0000", kind="expense")

    with database.session_factory() as db:
        user = db.scalar(select(User).where(User.normalized_username == "owner"))
        assert user is not None
        baseline_date = today - timedelta(days=29)
        db.add(_financial_snapshot(user.id, baseline_date, "3500", "4500"))
        db.add_all(
            [
                AccountBalanceSnapshot(
                    user_id=user.id,
                    account_id=checking_id,
                    snapshot_date=baseline_date,
                    account_name="Checking",
                    institution_name=None,
                    account_type="depository",
                    account_subtype="checking",
                    source_type="manual",
                    balance=Decimal("4500"),
                    available_balance=Decimal("4500"),
                    credit_limit=None,
                    currency="USD",
                ),
                AccountBalanceSnapshot(
                    user_id=user.id,
                    account_id=credit_id,
                    snapshot_date=baseline_date,
                    account_name="Rewards Card",
                    institution_name=None,
                    account_type="credit",
                    account_subtype="credit card",
                    source_type="manual",
                    balance=Decimal("-1000"),
                    available_balance=None,
                    credit_limit=Decimal("5000"),
                    currency="USD",
                ),
            ]
        )
        capture_snapshot(db, user)
        db.commit()

    response = client.get("/api/v1/trends?range=30d")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["currency"] == "USD"
    assert body["summary"]["net_worth"] == "4000.0000"
    assert body["summary"]["assets"] == "5000.0000"
    assert body["summary"]["liabilities"] == "1000.0000"
    assert body["summary"]["change_amount"] == "500.0000"
    assert len(body["net_worth_history"]) >= 2
    assert body["balance_history"][-1]["net_worth"] == "4000.0000"

    checking = next(row for row in body["account_contributions"] if row["account_id"] == checking_id)
    assert checking["history_available"] is True
    assert checking["start_balance"] == "4500.0000"
    assert checking["change_amount"] == "500.0000"

    groceries = next(row for row in body["spending_categories"] if row["key"] == "groceries")
    assert groceries["current"] == "500.0000"
    assert groceries["previous"] == "400.0000"
    payroll = next(row for row in body["income_sources"] if row["label"] == "Payroll")
    assert payroll["current"] == "3000.0000"
    assert payroll["previous"] == "2500.0000"
    assert body["history"]["account_tracking_active"] is True
    assert body["history"]["account_snapshot_days"] == 2


def test_trends_rejects_unknown_range(authenticated) -> None:
    client, _ = authenticated
    assert client.get("/api/v1/trends?range=decade").status_code == 422


def test_trends_does_not_invent_range_or_ytd_baselines(authenticated, database) -> None:
    client, csrf = authenticated
    checking_id = _account(client, csrf, name="New Checking", balance="5000.0000")
    today = datetime.now(ZoneInfo("America/Chicago")).date()

    with database.session_factory() as db:
        user = db.scalar(select(User).where(User.normalized_username == "owner"))
        assert user is not None
        db.add(
            AccountBalanceSnapshot(
                user_id=user.id,
                account_id=checking_id,
                snapshot_date=today - timedelta(days=2),
                account_name="New Checking",
                institution_name=None,
                account_type="depository",
                account_subtype="checking",
                source_type="manual",
                balance=Decimal("4800.0000"),
                available_balance=Decimal("4800.0000"),
                credit_limit=None,
                currency="USD",
            )
        )
        capture_snapshot(db, user)
        db.commit()

    response = client.get("/api/v1/trends?range=30d")
    assert response.status_code == 200, response.text
    body = response.json()
    contribution = next(
        row for row in body["account_contributions"] if row["account_id"] == checking_id
    )
    assert contribution["history_available"] is False
    assert contribution["start_balance"] is None
    assert contribution["change_amount"] is None
    assert body["summary"]["ytd_change_percent"] is None
