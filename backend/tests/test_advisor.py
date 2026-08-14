from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from contextlib import contextmanager

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app.api import advisor as advisor_api
from app.core.errors import ApiError
from app.core.security import utc_now
from app.models import Account, AdvisorConversation, AdvisorMessage, Category, InsightRecord, Transaction, User
from app.services.advisor import (
    TOOL_DEFINITIONS,
    _spending_trends_by_category,
    reset_advisor_rate_limits_for_testing,
    sanitized_snapshot,
    trusted_facts,
)
from tests.conftest import csrf_headers


class FakeProvider:
    def plan(self, **kwargs):
        assert "access_token" not in json.dumps(kwargs["snapshot"])
        return [{"name": "evaluate_purchase", "arguments": {"amount": 100}}]

    def stream_answer(self, **kwargs) -> Iterator[tuple[str, object]]:
        yield "delta", "Yes, "
        yield "delta", "based on your current plan."
        yield "done", {
            "mode": kwargs["mode"],
            "headline": "The purchase fits the current plan",
            "answer": "Yes, based on your current plan.",
            "confidence": "high",
            "warnings": [],
            "suggested_questions": ["What if I spend more?"],
        }


def _enable_provider(client: TestClient) -> None:
    client.app.state.settings.ai_enabled = True
    client.app.state.settings.openai_api_key = SecretStr("test-key")


def test_advisor_streams_deterministic_facts_and_stores_history(authenticated, monkeypatch) -> None:
    client, csrf = authenticated
    _enable_provider(client)
    monkeypatch.setattr(advisor_api, "provider_for_settings", lambda settings: FakeProvider())
    reset_advisor_rate_limits_for_testing()

    created = client.post("/api/v1/advisor/conversations", headers=csrf_headers(csrf), json={})
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]

    response = client.post(
        f"/api/v1/advisor/conversations/{conversation_id}/messages/stream",
        headers=csrf_headers(csrf),
        json={"message": "Can I afford a $100 purchase?", "insight_id": None},
    )
    assert response.status_code == 200, response.text
    assert "event: delta" in response.text
    assert "event: done" in response.text
    assert "Safe to spend" in response.text

    detail = client.get(f"/api/v1/advisor/conversations/{conversation_id}")
    assert detail.status_code == 200
    assert [item["role"] for item in detail.json()["messages"]] == ["user", "assistant"]
    assert detail.json()["messages"][1]["response"]["confidence"] == "high"


def test_advisor_private_mode_keeps_no_history(authenticated, database, monkeypatch) -> None:
    client, csrf = authenticated
    _enable_provider(client)
    monkeypatch.setattr(advisor_api, "provider_for_settings", lambda settings: FakeProvider())
    reset_advisor_rate_limits_for_testing()
    patch = client.patch("/api/v1/settings", headers=csrf_headers(csrf), json={"advisor_store_history": False})
    assert patch.status_code == 200

    created = client.post("/api/v1/advisor/conversations", headers=csrf_headers(csrf), json={})
    conversation_id = created.json()["id"]
    response = client.post(
        f"/api/v1/advisor/conversations/{conversation_id}/messages/stream",
        headers=csrf_headers(csrf),
        json={"message": "What should I focus on?", "insight_id": None},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/advisor/conversations").json()["conversations"] == []
    with database.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AdvisorMessage)) == 0
        assert db.scalar(select(func.count()).select_from(AdvisorConversation)) == 0


def test_advisor_settings_are_non_nullable_and_disable_access(authenticated) -> None:
    client, csrf = authenticated
    null_patch = client.patch("/api/v1/settings", headers=csrf_headers(csrf), json={"advisor_enabled": None})
    assert null_patch.status_code == 422
    disabled = client.patch("/api/v1/settings", headers=csrf_headers(csrf), json={"advisor_enabled": False})
    assert disabled.status_code == 200
    response = client.post("/api/v1/advisor/conversations", headers=csrf_headers(csrf), json={})
    assert response.status_code == 403


def test_snapshot_redacts_recurring_merchant_insight_until_opt_in(authenticated, database) -> None:
    client, csrf = authenticated
    with database.session_factory() as db:
        user_id = client.get("/api/v1/auth/me").json()["user"]["id"]
        from app.core.security import utc_now
        row = InsightRecord(
            user_id=user_id,
            fingerprint="f" * 64,
            signal_type="recurring_price_increase",
            category="recurring",
            priority="important",
            score=80,
            status="active",
            title="Netflix increased 25%",
            summary="Netflix moved from one amount to another.",
            recommendation="Review it.",
            evidence_json="[]",
            action_route="/recurring",
            first_seen_at=utc_now(),
            last_seen_at=utc_now(),
        )
        db.add(row); db.commit()
        user = db.get(__import__('app.models', fromlist=['User']).User, user_id)
        snapshot = sanitized_snapshot(db, user)
        assert "Netflix" not in json.dumps(snapshot)

    opted = client.patch("/api/v1/settings", headers=csrf_headers(csrf), json={"advisor_share_merchants": True})
    assert opted.status_code == 200
    with database.session_factory() as db:
        user = db.get(__import__('app.models', fromlist=['User']).User, user_id)
        snapshot = sanitized_snapshot(db, user)
        assert "Netflix" in json.dumps(snapshot)


def test_advisor_local_rate_limit_returns_retry_after(authenticated, monkeypatch) -> None:
    client, csrf = authenticated
    _enable_provider(client)
    client.app.state.settings.ai_requests_per_minute = 1
    monkeypatch.setattr(advisor_api, "provider_for_settings", lambda settings: FakeProvider())
    reset_advisor_rate_limits_for_testing()
    first = client.post("/api/v1/advisor/conversations", headers=csrf_headers(csrf), json={})
    cid = first.json()["id"]
    assert client.post(f"/api/v1/advisor/conversations/{cid}/messages/stream", headers=csrf_headers(csrf), json={"message":"hello","insight_id":None}).status_code == 200
    response = client.post(f"/api/v1/advisor/conversations/{cid}/messages/stream", headers=csrf_headers(csrf), json={"message":"again","insight_id":None})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1


def test_all_advisor_tools_are_strict_read_only_shapes() -> None:
    names = {tool["name"] for tool in TOOL_DEFINITIONS}
    assert names
    assert not any(any(word in str(name) for word in ("create", "update", "delete", "transfer", "write")) for name in names)
    for tool in TOOL_DEFINITIONS:
        assert tool["type"] == "function"
        assert tool["strict"] is True
        schema = tool["parameters"]
        assert schema["additionalProperties"] is False
        assert set(schema.get("required", [])) == set(schema.get("properties", {}))


class FailingPlanProvider:
    def plan(self, **kwargs):
        raise ApiError(503, "advisor_provider_unavailable", "Provider unavailable")

    def stream_answer(self, **kwargs):  # pragma: no cover - planning fails first
        yield from ()


def test_private_mode_cleans_transient_conversation_when_planning_fails(authenticated, database, monkeypatch) -> None:
    client, csrf = authenticated
    _enable_provider(client)
    reset_advisor_rate_limits_for_testing()
    assert client.patch(
        "/api/v1/settings", headers=csrf_headers(csrf), json={"advisor_store_history": False}
    ).status_code == 200
    monkeypatch.setattr(advisor_api, "provider_for_settings", lambda settings: FailingPlanProvider())

    created = client.post("/api/v1/advisor/conversations", headers=csrf_headers(csrf), json={})
    assert created.status_code == 201
    response = client.post(
        f"/api/v1/advisor/conversations/{created.json()['id']}/messages/stream",
        headers=csrf_headers(csrf),
        json={"message": "Help me", "insight_id": None},
    )
    assert response.status_code == 503
    with database.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AdvisorConversation)) == 0
        assert db.scalar(select(func.count()).select_from(AdvisorMessage)) == 0


def test_spending_trends_compare_same_days_and_surface_top_increase(authenticated, database) -> None:
    client, _ = authenticated
    user_id = client.get("/api/v1/auth/me").json()["user"]["id"]
    with database.session_factory() as db:
        user = db.get(User, user_id)
        assert user is not None
        categories = {row.stable_key: row for row in db.scalars(select(Category).where(Category.user_id == user_id)).all()}
        account = Account(
            user_id=user_id,
            name="Trend Checking",
            account_type="depository",
            current_balance=Decimal("5000"),
            available_balance=Decimal("5000"),
            currency="USD",
        )
        db.add(account)
        db.flush()
        rows = [
            ("jul-restaurants", date(2026, 7, 5), "restaurants", "-100"),
            ("aug-restaurants", date(2026, 8, 5), "restaurants", "-180"),
            ("jul-groceries", date(2026, 7, 7), "groceries", "-200"),
            ("aug-groceries", date(2026, 8, 7), "groceries", "-150"),
            ("aug-housing", date(2026, 8, 12), "housing", "-50"),
            # This is outside the same-day comparison window and must not inflate July.
            ("jul-late-restaurants", date(2026, 7, 20), "restaurants", "-999"),
        ]
        for external_id, posted, category_key, amount in rows:
            db.add(
                Transaction(
                    user_id=user_id,
                    account_id=account.id,
                    category_id=categories[category_key].id,
                    external_id=external_id,
                    posted_date=posted,
                    description=external_id,
                    merchant="Trend Test",
                    amount=Decimal(amount),
                    kind="expense",
                    pending=False,
                    imported_at=utc_now(),
                )
            )
        db.commit()

        result = _spending_trends_by_category(db, user, date(2026, 8, 13))

    assert result["basis"] == "month_to_date_same_days"
    assert result["current_period"] == {"from": "2026-08-01", "through": "2026-08-13"}
    assert result["comparison_period"] == {"from": "2026-07-01", "through": "2026-07-13"}
    top = result["top_increases"][0]
    assert top["category"] == "Restaurants"
    assert top["current_amount"] == "180.0000"
    assert top["previous_amount"] == "100.0000"
    assert top["change_amount"] == "80.0000"
    assert top["change_percent"] == "80.00"

    facts = trusted_facts(
        {"currency": "USD", "budget": {"safe_to_spend": "1000.0000", "cash_available": "2000.0000"}},
        [{"name": "get_spending_trends_by_category", "result": result}],
    )
    trend_fact = next(item for item in facts if item["label"] == "Top spending increase")
    assert "Restaurants" in trend_fact["value"]
    assert "80.00%" in trend_fact["detail"]
