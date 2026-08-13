from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import Database
from app.core.security import utc_now
from app.models import Account, Category, Transaction, User
from tests.conftest import csrf_headers


def _category_ids(client: TestClient) -> dict[str, int]:
    response = client.get("/api/v1/categories/selection")
    assert response.status_code == 200
    return {item["key"]: item["id"] for item in response.json()["categories"]}


def _annual_payload(ids: dict[str, int]) -> dict[str, object]:
    custom = [{"month": month, "amount": "50.0000" if month < 12 else "650.0000"} for month in range(1, 13)]
    return {
        "planned_income": "60000.0000",
        "notes": "Base annual plan",
        "categories": [
            {
                "category_id": ids["housing"],
                "annual_amount": "12000.0000",
                "distribution": "even",
                "monthly_amount": None,
                "custom_months": [],
                "rollover_mode": "off",
            },
            {
                "category_id": ids["groceries"],
                "annual_amount": "0",
                "distribution": "monthly",
                "monthly_amount": "500.0000",
                "custom_months": [],
                "rollover_mode": "surplus",
            },
            {
                "category_id": ids["restaurants"],
                "annual_amount": "0",
                "distribution": "custom",
                "monthly_amount": None,
                "custom_months": custom,
                "rollover_mode": "surplus_and_deficit",
            },
        ],
    }


def _add_january_finance_data(database: Database) -> None:
    with database.session_factory() as db:
        user = db.scalar(select(User).where(User.normalized_username == "owner"))
        assert user is not None
        categories = {
            category.stable_key: category
            for category in db.scalars(select(Category).where(Category.user_id == user.id)).all()
        }
        account = Account(
            user_id=user.id,
            name="Budget Checking",
            account_type="depository",
            source_type="manual",
            current_balance=Decimal("3000"),
            available_balance=Decimal("3000"),
            currency="USD",
        )
        db.add(account)
        db.flush()
        for external, category, amount, kind in (
            ("budget-pay", "income", "5000", "income"),
            ("budget-rent", "housing", "-1000", "expense"),
            ("budget-grocery", "groceries", "-400", "expense"),
            ("budget-dinner", "restaurants", "-75", "expense"),
        ):
            db.add(
                Transaction(
                    user_id=user.id,
                    account_id=account.id,
                    category_id=categories[category].id,
                    external_id=external,
                    posted_date=date(2026, 1, 15),
                    description=external,
                    amount=Decimal(amount),
                    kind=kind,
                    source_type="manual",
                    pending=False,
                    imported_at=utc_now(),
                )
            )
        db.commit()


def test_annual_monthly_rollover_copy_and_year_views(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    headers = csrf_headers(csrf)
    ids = _category_ids(client)

    saved = client.put(
        "/api/v1/budget/years/2026/plan", json=_annual_payload(ids), headers=headers
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["exists"] is True
    assert body["planned_income"] == "60000.0000"
    grocery = next(item for item in body["categories"] if item["category"]["key"] == "groceries")
    assert grocery["annual_amount"] == "6000.0000"
    restaurants = next(item for item in body["categories"] if item["category"]["key"] == "restaurants")
    assert restaurants["annual_amount"] == "1200.0000"
    assert restaurants["custom_months"][-1]["amount"] == "650.0000"

    _add_january_finance_data(database)
    january = client.get("/api/v1/budget/months/2026-01")
    assert january.status_code == 200
    jan = january.json()
    assert jan["source"] == "annual"
    assert jan["planned_income"] == "5000.0000"
    assert jan["actual_income"] == "5000.0000"
    assert jan["cash_available"] == "3000.0000"
    jan_grocery = next(item for item in jan["categories"] if item["category"]["key"] == "groceries")
    assert jan_grocery["base_amount"] == "500.0000"
    assert jan_grocery["spent_amount"] == "400.0000"
    assert jan_grocery["remaining_amount"] == "100.0000"

    february = client.get("/api/v1/budget/months/2026-02").json()
    feb_grocery = next(item for item in february["categories"] if item["category"]["key"] == "groceries")
    assert feb_grocery["rollover_amount"] == "100.0000"
    assert feb_grocery["available_amount"] == "600.0000"

    override = client.put(
        "/api/v1/budget/months/2026-02",
        headers=headers,
        json={
            "mode": "override",
            "planned_income": "5200.0000",
            "notes": "Travel month",
            "categories": [
                {
                    "category_id": ids["groceries"],
                    "planned_amount": "700.0000",
                    "rollover_mode": "surplus",
                }
            ],
        },
    )
    assert override.status_code == 200, override.text
    override_body = override.json()
    assert override_body["source"] == "override"
    assert override_body["planned_income"] == "5200.0000"
    overridden_grocery = next(
        item for item in override_body["categories"] if item["category"]["key"] == "groceries"
    )
    inherited_housing = next(
        item for item in override_body["categories"] if item["category"]["key"] == "housing"
    )
    assert overridden_grocery["base_amount"] == "700.0000"
    assert inherited_housing["base_amount"] == "1000.0000"

    copied = client.post("/api/v1/budget/months/2026-03/copy-previous", headers=headers)
    assert copied.status_code == 200, copied.text
    copied_body = copied.json()
    assert copied_body["source"] == "standalone"
    assert copied_body["planned_income"] == "5200.0000"
    copied_grocery = next(
        item for item in copied_body["categories"] if item["category"]["key"] == "groceries"
    )
    assert copied_grocery["base_amount"] == "700.0000"

    cleared = client.delete("/api/v1/budget/months/2026-03", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["source"] == "annual"

    year = client.get("/api/v1/budget/years/2026")
    assert year.status_code == 200
    year_body = year.json()
    assert year_body["has_annual_plan"] is True
    assert Decimal(year_body["planned_income"]) > Decimal("60000")
    assert Decimal(year_body["spent"]) == Decimal("1475.0000")


def test_budget_validation_and_unplanned_states(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    headers = csrf_headers(csrf)
    ids = _category_ids(client)

    unplanned = client.get("/api/v1/budget/months/2027-01")
    assert unplanned.status_code == 200
    assert unplanned.json()["source"] == "unplanned"

    invalid_override = client.put(
        "/api/v1/budget/months/2027-01",
        headers=headers,
        json={"mode": "override", "planned_income": None, "notes": None, "categories": []},
    )
    assert invalid_override.status_code == 422
    assert invalid_override.json()["error"]["code"] == "annual_plan_required"

    duplicate = client.put(
        "/api/v1/budget/years/2027/plan",
        headers=headers,
        json={
            "planned_income": "10000",
            "notes": None,
            "categories": [
                {"category_id": ids["housing"], "annual_amount": "1000", "distribution": "even", "monthly_amount": None, "custom_months": [], "rollover_mode": "off"},
                {"category_id": ids["housing"], "annual_amount": "2000", "distribution": "even", "monthly_amount": None, "custom_months": [], "rollover_mode": "off"},
            ],
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "duplicate_budget_category"
