from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from tests.conftest import csrf_headers


def _manual_account(
    client: TestClient, csrf: str, *, name: str, account_type: str, balance: str
) -> int:
    response = client.post(
        "/api/v1/accounts",
        headers=csrf_headers(csrf),
        json={
            "name": name,
            "official_name": None,
            "account_type": account_type,
            "account_subtype": None,
            "current_balance": balance,
            "available_balance": balance if account_type == "depository" else None,
            "credit_limit": None,
            "currency": "USD",
            "mask_last4": None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_goals_debts_forecast_and_scenario(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    headers = csrf_headers(csrf)
    savings_id = _manual_account(
        client, csrf, name="Goal Savings", account_type="depository", balance="2400.0000"
    )
    loan_id = _manual_account(
        client, csrf, name="Auto Loan", account_type="loan", balance="-8200.0000"
    )

    linked_goal = client.post(
        "/api/v1/planning/goals",
        headers=headers,
        json={
            "name": "Emergency fund",
            "goal_type": "emergency_fund",
            "target_amount": "10000.0000",
            "current_amount": "0",
            "monthly_contribution": "500.0000",
            "target_date": None,
            "linked_account_id": savings_id,
            "priority": 10,
            "active": True,
            "notes": None,
        },
    )
    assert linked_goal.status_code == 201, linked_goal.text
    linked = linked_goal.json()["goals"][0]
    assert linked["current_amount"] == "2400.0000"
    assert linked["progress_pct"] == "24.0000"
    assert linked["projected_date"] is not None

    duplicate_link = client.post(
        "/api/v1/planning/goals",
        headers=headers,
        json={
            "name": "Second account goal",
            "goal_type": "savings",
            "target_amount": "5000.0000",
            "current_amount": "0",
            "monthly_contribution": "100.0000",
            "target_date": None,
            "linked_account_id": savings_id,
            "priority": 30,
            "active": True,
            "notes": None,
        },
    )
    assert duplicate_link.status_code == 422
    assert duplicate_link.json()["error"]["code"] == "goal_account_already_linked"

    manual_goal = client.post(
        "/api/v1/planning/goals",
        headers=headers,
        json={
            "name": "Vacation",
            "goal_type": "vacation",
            "target_amount": "3000.0000",
            "current_amount": "500.0000",
            "monthly_contribution": "250.0000",
            "target_date": None,
            "linked_account_id": None,
            "priority": 20,
            "active": True,
            "notes": None,
        },
    )
    assert manual_goal.status_code == 201
    vacation = next(item for item in manual_goal.json()["goals"] if item["name"] == "Vacation")
    contribution = client.post(
        f"/api/v1/planning/goals/{vacation['id']}/contributions",
        headers=headers,
        json={"amount": "100.0000", "contribution_date": date.today().isoformat(), "notes": None},
    )
    assert contribution.status_code == 200, contribution.text
    vacation = next(item for item in contribution.json()["goals"] if item["name"] == "Vacation")
    assert vacation["current_amount"] == "600.0000"

    debt = client.post(
        "/api/v1/planning/debts",
        headers=headers,
        json={
            "name": "Auto loan",
            "debt_type": "auto",
            "balance": "8200.0000",
            "apr": "7.2000",
            "minimum_payment": "325.0000",
            "extra_payment": "75.0000",
            "linked_account_id": loan_id,
            "strategy_priority": 10,
            "due_day": 20,
            "active": True,
            "notes": None,
        },
    )
    assert debt.status_code == 201, debt.text
    debt_body = debt.json()
    assert debt_body["total_balance"] == "8200.0000"
    assert debt_body["debts"][0]["planned_payoff_date"] is not None

    strategy = client.put(
        "/api/v1/planning/debts/strategy",
        headers=headers,
        json={"strategy": "avalanche", "monthly_extra_budget": "200.0000"},
    )
    assert strategy.status_code == 200, strategy.text
    strategy_body = strategy.json()
    assert strategy_body["planned_monthly_payment"] == "600.0000"
    assert Decimal(strategy_body["interest_saved"]) >= Decimal("0")

    assumptions = client.put(
        "/api/v1/planning/forecast/assumptions",
        headers=headers,
        json={"reserve_balance": "1500.0000", "include_budget_reserve": True},
    )
    assert assumptions.status_code == 200, assumptions.text
    forecast = assumptions.json()
    assert forecast["cash_available"] == "2400.0000"
    assert forecast["goal_reserves"] == "2400.0000"
    assert forecast["spendable_cash"] == "0.0000"
    assert [item["days"] for item in forecast["horizons"]] == [30, 60, 90]

    month = forecast["as_of"][:7]
    budget = client.get(f"/api/v1/budget/months/{month}")
    assert budget.status_code == 200, budget.text
    assert budget.json()["planning_commitments"] == "1350.0000"
    assert budget.json()["goal_reserves"] == "2400.0000"
    assert budget.json()["safe_to_spend"] == "-1350.0000"

    scenario = client.post(
        "/api/v1/planning/forecast/scenario",
        headers=headers,
        json={
            "extra_debt_payment": "100.0000",
            "goal_contribution_adjustment": "-100.0000",
            "spending_reduction": "150.0000",
            "new_monthly_expense": "0",
        },
    )
    assert scenario.status_code == 200, scenario.text
    scenario_body = scenario.json()
    assert Decimal(scenario_body["interest_saved"]) >= Decimal("0")
    assert len(scenario_body["scenario"]["horizons"]) == 3


def test_planning_validation_and_owner_boundaries(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    headers = csrf_headers(csrf)

    invalid_goal = client.post(
        "/api/v1/planning/goals",
        headers=headers,
        json={
            "name": "Impossible",
            "goal_type": "savings",
            "target_amount": "0",
            "current_amount": "0",
            "monthly_contribution": "0",
            "target_date": None,
            "linked_account_id": None,
            "priority": 100,
            "active": True,
            "notes": None,
        },
    )
    assert invalid_goal.status_code == 422

    missing_goal = client.patch(
        "/api/v1/planning/goals/9999",
        headers=headers,
        json={"name": "Missing"},
    )
    assert missing_goal.status_code == 404
    assert missing_goal.json()["error"]["code"] == "goal_not_found"

    invalid_debt = client.post(
        "/api/v1/planning/debts",
        headers=headers,
        json={
            "name": "Bad APR",
            "debt_type": "other",
            "balance": "1000",
            "apr": "101",
            "minimum_payment": "50",
            "extra_payment": "0",
            "linked_account_id": None,
            "strategy_priority": 100,
            "due_day": None,
            "active": True,
            "notes": None,
        },
    )
    assert invalid_debt.status_code == 422

    no_debt_scenario = client.post(
        "/api/v1/planning/forecast/scenario",
        headers=headers,
        json={
            "extra_debt_payment": "500.0000",
            "goal_contribution_adjustment": "0",
            "spending_reduction": "0",
            "new_monthly_expense": "0",
        },
    )
    assert no_debt_scenario.status_code == 200, no_debt_scenario.text
    body = no_debt_scenario.json()
    assert body["cash_impact_90_days"] == "0.0000"
