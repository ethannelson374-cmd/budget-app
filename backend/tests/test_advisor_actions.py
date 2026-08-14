from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import advisor as advisor_api
from app.services.advisor import reset_advisor_rate_limits_for_testing
from tests.conftest import csrf_headers


def _enable_provider(client: TestClient) -> None:
    client.app.state.settings.ai_enabled = True
    client.app.state.settings.openai_api_key = SecretStr("test-key")


def _done_payload(text: str) -> dict[str, object]:
    for block in text.split("\n\n"):
        lines = block.splitlines()
        if lines and lines[0] == "event: done":
            data = next(line[6:] for line in lines if line.startswith("data: "))
            value = json.loads(data)
            assert isinstance(value, dict)
            return value
    raise AssertionError("done event missing")


class ActionProvider:
    def __init__(self, actions: list[dict[str, object]]) -> None:
        self.actions = actions

    def plan(self, **kwargs):
        return []

    def stream_answer(self, **kwargs) -> Iterator[tuple[str, object]]:
        yield "done", {
            "mode": kwargs["mode"],
            "headline": "Here is a plan you can review",
            "answer": "I built a small plan. Budget will calculate the impact and will not apply anything until you approve it.",
            "confidence": "high",
            "warnings": [],
            "suggested_questions": ["What if I change the amounts?"],
            "action_plan_title": "Free up monthly cash",
            "action_plan_summary": "Adjust the current budget, savings contribution, debt plan, and reserve target.",
            "proposed_actions": self.actions,
        }


def _create_conversation(client: TestClient, csrf: str) -> int:
    response = client.post("/api/v1/advisor/conversations", headers=csrf_headers(csrf), json={})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_advisor_action_plan_previews_applies_and_undoes_existing_domain_settings(authenticated, monkeypatch) -> None:
    client, csrf = authenticated
    _enable_provider(client)
    reset_advisor_rate_limits_for_testing()

    categories = client.get("/api/v1/categories/selection").json()["categories"]
    groceries_id = next(item["id"] for item in categories if item["key"] == "groceries")
    month = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m")
    budget = client.put(
        f"/api/v1/budget/months/{month}",
        headers=csrf_headers(csrf),
        json={
            "mode": "standalone",
            "planned_income": "5000",
            "notes": "Advisor action test",
            "categories": [{"category_id": groceries_id, "planned_amount": "500", "rollover_mode": "off"}],
        },
    )
    assert budget.status_code == 200, budget.text

    goals = client.post(
        "/api/v1/planning/goals",
        headers=csrf_headers(csrf),
        json={
            "name": "Emergency Fund",
            "goal_type": "emergency_fund",
            "target_amount": "10000",
            "current_amount": "1000",
            "monthly_contribution": "200",
            "priority": 10,
        },
    )
    assert goals.status_code == 201, goals.text
    goal_id = goals.json()["goals"][0]["id"]

    debts = client.post(
        "/api/v1/planning/debts",
        headers=csrf_headers(csrf),
        json={
            "name": "Rewards Card",
            "debt_type": "credit_card",
            "balance": "2000",
            "apr": "20",
            "minimum_payment": "75",
            "extra_payment": "25",
            "strategy_priority": 10,
        },
    )
    assert debts.status_code == 201, debts.text
    debt_id = debts.json()["debts"][0]["id"]

    reserve = client.put(
        "/api/v1/planning/forecast/assumptions",
        headers=csrf_headers(csrf),
        json={"reserve_balance": "250", "include_budget_reserve": True},
    )
    assert reserve.status_code == 200, reserve.text

    actions = [
        {
            "action_type": "budget_category_monthly_set",
            "target_id": groceries_id,
            "value": "350",
            "secondary_value": month,
            "rationale": "Lower the grocery target for this month.",
        },
        {
            "action_type": "goal_monthly_contribution_set",
            "target_id": goal_id,
            "value": "350",
            "secondary_value": "",
            "rationale": "Increase the emergency fund contribution.",
        },
        {
            "action_type": "debt_extra_payment_set",
            "target_id": debt_id,
            "value": "100",
            "secondary_value": "",
            "rationale": "Direct more cash to the card.",
        },
        {
            "action_type": "debt_strategy_set",
            "target_id": 0,
            "value": "snowball",
            "secondary_value": "150",
            "rationale": "Use a focused monthly debt budget.",
        },
        {
            "action_type": "forecast_reserve_set",
            "target_id": 0,
            "value": "1000",
            "secondary_value": "false",
            "rationale": "Keep a larger explicit cash reserve.",
        },
    ]
    monkeypatch.setattr(advisor_api, "provider_for_settings", lambda settings: ActionProvider(actions))

    conversation_id = _create_conversation(client, csrf)
    response = client.post(
        f"/api/v1/advisor/conversations/{conversation_id}/messages/stream",
        headers=csrf_headers(csrf),
        json={"message": "Build me a plan to free up cash", "insight_id": None},
    )
    assert response.status_code == 200, response.text
    done = _done_payload(response.text)
    proposal_id = done["proposal_id"]
    assert isinstance(proposal_id, int)
    assert "proposed_actions" not in done

    proposal = client.get(f"/api/v1/advisor/proposals/{proposal_id}")
    assert proposal.status_code == 200, proposal.text
    body = proposal.json()
    assert body["status"] == "draft"
    assert len(body["actions"]) == 5
    assert body["preview"]["impacts"]

    # Previewing must never mutate the live financial plan.
    assert next(item for item in client.get(f"/api/v1/budget/months/{month}").json()["categories"] if item["category"]["id"] == groceries_id)["base_amount"] == "500.0000"
    assert next(item for item in client.get("/api/v1/planning/goals").json()["goals"] if item["id"] == goal_id)["monthly_contribution"] == "200.0000"
    assert next(item for item in client.get("/api/v1/planning/debts").json()["debts"] if item["id"] == debt_id)["extra_payment"] == "25.0000"

    applied = client.post(f"/api/v1/advisor/proposals/{proposal_id}/apply", headers=csrf_headers(csrf))
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"

    budget_after = client.get(f"/api/v1/budget/months/{month}").json()
    assert next(item for item in budget_after["categories"] if item["category"]["id"] == groceries_id)["base_amount"] == "350.0000"
    goals_after = client.get("/api/v1/planning/goals").json()
    assert next(item for item in goals_after["goals"] if item["id"] == goal_id)["monthly_contribution"] == "350.0000"
    debts_after = client.get("/api/v1/planning/debts").json()
    debt_after = next(item for item in debts_after["debts"] if item["id"] == debt_id)
    assert debt_after["extra_payment"] == "100.0000"
    assert debts_after["strategy"] == "snowball"
    assert debts_after["monthly_extra_budget"] == "150.0000"
    forecast_after = client.get("/api/v1/planning/forecast").json()
    assert forecast_after["reserve_balance"] == "1000.0000"
    assert forecast_after["include_budget_reserve"] is False

    undone = client.post(f"/api/v1/advisor/proposals/{proposal_id}/undo", headers=csrf_headers(csrf))
    assert undone.status_code == 200, undone.text
    assert undone.json()["status"] == "undone"
    assert next(item for item in client.get(f"/api/v1/budget/months/{month}").json()["categories"] if item["category"]["id"] == groceries_id)["base_amount"] == "500.0000"
    assert next(item for item in client.get("/api/v1/planning/goals").json()["goals"] if item["id"] == goal_id)["monthly_contribution"] == "200.0000"
    debts_restored = client.get("/api/v1/planning/debts").json()
    assert next(item for item in debts_restored["debts"] if item["id"] == debt_id)["extra_payment"] == "25.0000"
    assert debts_restored["strategy"] == "avalanche"
    assert debts_restored["monthly_extra_budget"] == "0.0000"
    forecast_restored = client.get("/api/v1/planning/forecast").json()
    assert forecast_restored["reserve_balance"] == "250.0000"
    assert forecast_restored["include_budget_reserve"] is True


def test_advisor_action_plan_refuses_stale_apply_and_can_be_dismissed(authenticated, monkeypatch) -> None:
    client, csrf = authenticated
    _enable_provider(client)
    reset_advisor_rate_limits_for_testing()
    goals = client.post(
        "/api/v1/planning/goals",
        headers=csrf_headers(csrf),
        json={"name": "Trip", "goal_type": "vacation", "target_amount": "3000", "current_amount": "0", "monthly_contribution": "100"},
    )
    goal_id = goals.json()["goals"][0]["id"]
    monkeypatch.setattr(advisor_api, "provider_for_settings", lambda settings: ActionProvider([{
        "action_type": "goal_monthly_contribution_set",
        "target_id": goal_id,
        "value": "250",
        "secondary_value": "",
        "rationale": "Save faster.",
    }]))
    cid = _create_conversation(client, csrf)
    response = client.post(
        f"/api/v1/advisor/conversations/{cid}/messages/stream",
        headers=csrf_headers(csrf),
        json={"message": "Help me save faster", "insight_id": None},
    )
    proposal_id = _done_payload(response.text)["proposal_id"]
    assert isinstance(proposal_id, int)

    changed = client.patch(
        f"/api/v1/planning/goals/{goal_id}", headers=csrf_headers(csrf), json={"monthly_contribution": "175"}
    )
    assert changed.status_code == 200
    stale = client.post(f"/api/v1/advisor/proposals/{proposal_id}/apply", headers=csrf_headers(csrf))
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "advisor_proposal_stale"

    dismissed = client.post(f"/api/v1/advisor/proposals/{proposal_id}/reject", headers=csrf_headers(csrf))
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "rejected"
    second_apply = client.post(f"/api/v1/advisor/proposals/{proposal_id}/apply", headers=csrf_headers(csrf))
    assert second_apply.status_code == 409


def test_private_advisor_session_does_not_persist_action_plan(authenticated, monkeypatch) -> None:
    client, csrf = authenticated
    _enable_provider(client)
    reset_advisor_rate_limits_for_testing()
    assert client.patch(
        "/api/v1/settings", headers=csrf_headers(csrf), json={"advisor_store_history": False}
    ).status_code == 200
    monkeypatch.setattr(advisor_api, "provider_for_settings", lambda settings: ActionProvider([{
        "action_type": "forecast_reserve_set",
        "target_id": 0,
        "value": "1000",
        "secondary_value": "true",
        "rationale": "Keep more cash on hand.",
    }]))
    cid = _create_conversation(client, csrf)
    response = client.post(
        f"/api/v1/advisor/conversations/{cid}/messages/stream",
        headers=csrf_headers(csrf),
        json={"message": "Build a reserve plan", "insight_id": None},
    )
    assert response.status_code == 200
    assert _done_payload(response.text)["proposal_id"] is None
