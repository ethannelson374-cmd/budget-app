from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    AnnualBudgetPlan,
    FinancialGoal,
    InsightRecord,
    MonthlyBudget,
    User,
    UserDashboardPreference,
)
from app.models.base import utc_now

CARD_DEFAULTS: tuple[dict[str, object], ...] = (
    {"id": "net_worth", "size": "small", "visible": True},
    {"id": "cash_available", "size": "small", "visible": True},
    {"id": "income", "size": "small", "visible": True},
    {"id": "spending", "size": "small", "visible": True},
    {"id": "net_cash_flow", "size": "small", "visible": True},
    {"id": "savings_rate", "size": "small", "visible": True},
    {"id": "cash_flow", "size": "wide", "visible": True},
    {"id": "top_spending", "size": "medium", "visible": True},
    {"id": "ask_budget", "size": "wide", "visible": True},
    {"id": "budget", "size": "large", "visible": True},
    {"id": "insights", "size": "large", "visible": True},
    {"id": "recent_transactions", "size": "large", "visible": True},
    {"id": "accounts", "size": "large", "visible": True},
    {"id": "data_freshness", "size": "medium", "visible": True},
)


def _normalized_cards(raw: object) -> list[dict[str, object]]:
    defaults = {str(item["id"]): dict(item) for item in CARD_DEFAULTS}
    order: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            card_id = str(item.get("id") or "")
            if card_id not in defaults or card_id in order:
                continue
            size = str(item.get("size") or defaults[card_id]["size"])
            if size not in {"small", "medium", "wide", "large"}:
                size = str(defaults[card_id]["size"])
            defaults[card_id] = {
                "id": card_id,
                "size": size,
                "visible": bool(item.get("visible", True)),
            }
            order.append(card_id)
    order.extend(card_id for card_id in defaults if card_id not in order)
    return [defaults[card_id] for card_id in order]


def dashboard_preferences(db: Session, user: User) -> dict[str, object]:
    row = db.get(UserDashboardPreference, user.id)
    cards: object = None
    preset = "everyday"
    dismissed_at: datetime | None = None
    if row is not None:
        preset = row.preset
        dismissed_at = row.onboarding_dismissed_at
        try:
            cards = json.loads(row.layout_json)
        except (TypeError, ValueError):
            cards = None
    return {
        "cards": _normalized_cards(cards),
        "preset": preset,
        "onboarding_dismissed_at": dismissed_at,
    }


def save_dashboard_preferences(
    db: Session,
    user: User,
    *,
    cards: list[dict[str, object]],
    preset: str,
) -> dict[str, object]:
    normalized = _normalized_cards(cards)
    row = db.get(UserDashboardPreference, user.id)
    if row is None:
        row = UserDashboardPreference(
            user_id=user.id,
            layout_json="[]",
            preset=preset,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(row)
    row.layout_json = json.dumps(normalized, separators=(",", ":"))
    row.preset = preset
    row.updated_at = utc_now()
    db.flush()
    return dashboard_preferences(db, user)


def dismiss_onboarding(db: Session, user: User) -> dict[str, object]:
    row = db.get(UserDashboardPreference, user.id)
    if row is None:
        row = UserDashboardPreference(
            user_id=user.id,
            layout_json=json.dumps(list(CARD_DEFAULTS), separators=(",", ":")),
            preset="everyday",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(row)
    row.onboarding_dismissed_at = utc_now()
    row.updated_at = utc_now()
    db.flush()
    return onboarding_status(db, user)


def onboarding_status(db: Session, user: User) -> dict[str, object]:
    account_count = int(db.scalar(select(func.count(Account.id)).where(Account.user_id == user.id)) or 0)
    annual_budget_count = int(db.scalar(select(func.count(AnnualBudgetPlan.id)).where(AnnualBudgetPlan.user_id == user.id)) or 0)
    monthly_budget_count = int(db.scalar(select(func.count(MonthlyBudget.id)).where(MonthlyBudget.user_id == user.id)) or 0)
    goal_count = int(db.scalar(select(func.count(FinancialGoal.id)).where(FinancialGoal.user_id == user.id)) or 0)
    insight_count = int(db.scalar(select(func.count(InsightRecord.id)).where(InsightRecord.user_id == user.id)) or 0)
    income_ready = user.settings.annual_gross_income is not None and user.settings.annual_gross_income > 0
    tasks = [
        {"key": "account", "label": "Add or connect an account", "description": "Give Budget a balance to work with.", "route": "/accounts", "complete": account_count > 0},
        {"key": "income", "label": "Set your income", "description": "Add annual income and pay frequency in Settings.", "route": "/settings", "complete": income_ready},
        {"key": "budget", "label": "Create a budget", "description": "Set a yearly plan or customize a month.", "route": "/budget", "complete": annual_budget_count > 0 or monthly_budget_count > 0},
        {"key": "goal", "label": "Add a financial goal", "description": "Track an emergency fund, down payment, or another target.", "route": "/plan", "complete": goal_count > 0},
        {"key": "insights", "label": "Generate your first insights", "description": "Let Budget review the financial picture you have built.", "route": "/insights", "complete": insight_count > 0},
    ]
    completed = sum(1 for task in tasks if task["complete"])
    preference = db.get(UserDashboardPreference, user.id)
    dismissed_at = preference.onboarding_dismissed_at if preference else None
    return {
        "tasks": tasks,
        "completed": completed,
        "total": len(tasks),
        "complete": completed == len(tasks),
        "dismissed": dismissed_at is not None,
        "dismissed_at": dismissed_at,
    }
