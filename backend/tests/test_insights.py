from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from tests.conftest import csrf_headers


def _category_ids(client: TestClient) -> dict[str, int]:
    response = client.get("/api/v1/categories/selection")
    assert response.status_code == 200, response.text
    return {item["key"]: item["id"] for item in response.json()["categories"]}


def test_refresh_generates_explainable_budget_insight_and_dismissal_persists(
    authenticated: tuple[TestClient, str],
) -> None:
    client, csrf = authenticated
    headers = csrf_headers(csrf)
    categories = _category_ids(client)
    today = datetime.now(ZoneInfo("America/Chicago")).date()

    account = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "name": "Checking",
            "official_name": None,
            "account_type": "depository",
            "account_subtype": "checking",
            "current_balance": "1000.0000",
            "available_balance": "1000.0000",
            "credit_limit": None,
            "currency": "USD",
            "mask_last4": "1234",
        },
    )
    assert account.status_code == 201, account.text

    plan = client.put(
        f"/api/v1/budget/years/{today.year}/plan",
        headers=headers,
        json={
            "planned_income": "60000.0000",
            "notes": None,
            "categories": [
                {
                    "category_id": categories["restaurants"],
                    "annual_amount": "1200.0000",
                    "distribution": "even",
                    "monthly_amount": None,
                    "custom_months": [],
                    "rollover_mode": "off",
                }
            ],
        },
    )
    assert plan.status_code == 200, plan.text

    transaction = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "account_id": account.json()["id"],
            "category_id": categories["restaurants"],
            "posted_date": today.isoformat(),
            "authorized_date": None,
            "merchant": "Dinner Test",
            "description": "Dinner Test",
            "amount": "-250.0000",
            "kind": "expense",
            "pending": False,
            "notes": None,
        },
    )
    assert transaction.status_code == 201, transaction.text

    refreshed = client.post("/api/v1/insights/refresh", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    overspend = next(
        item for item in body["insights"] if item["signal_type"] == "category_overspend"
    )
    assert overspend["priority"] in {"important", "critical"}
    assert "Restaurants" in overspend["title"]
    assert overspend["recommendation"]
    assert {item["label"] for item in overspend["evidence"]} >= {
        "Spent",
        "Available",
        "Over plan",
    }
    assert overspend["action_route"] == "/budget"

    dismissed = client.patch(
        f"/api/v1/insights/{overspend['id']}",
        headers=headers,
        json={"status": "dismissed"},
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"

    refreshed_again = client.post("/api/v1/insights/refresh", headers=headers)
    assert refreshed_again.status_code == 200, refreshed_again.text
    assert all(item["id"] != overspend["id"] for item in refreshed_again.json()["insights"])
    assert refreshed_again.json()["dismissed_count"] >= 1

    history = client.get("/api/v1/insights?status=dismissed")
    assert history.status_code == 200, history.text
    assert any(item["id"] == overspend["id"] for item in history.json()["insights"])
