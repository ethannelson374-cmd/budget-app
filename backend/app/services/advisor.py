from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import utc_now
from app.models import (
    Account,
    AdvisorConversation,
    AdvisorMessage,
    Category,
    Debt,
    FinancialGoal,
    InsightRecord,
    RecurringStream,
    Transaction,
    User,
)
from app.services.budget_planning import month_budget_view
from app.services.financial_planning import forecast_view, list_debts, list_goals, scenario_view
from app.services.insights import insight_view, list_insights
from app.services.transaction_intelligence import effective_category, effective_kind, effective_merchant

AdvisorMode = Literal["quick", "analysis", "scenario"]

_REQUESTS: dict[int, deque[float]] = defaultdict(deque)
_REQUEST_LOCK = threading.Lock()


def infer_mode(message: str) -> AdvisorMode:
    text = message.casefold()
    if any(token in text for token in ("what if", "if i ", "scenario", "afford", "extra", "instead")):
        return "scenario"
    if any(token in text for token in ("why", "trend", "compare", "last three", "last 3", "analy", "where")):
        return "analysis"
    return "quick"


def reserve_advisor_request(user_id: int, limit: int) -> int | None:
    now = time.monotonic()
    with _REQUEST_LOCK:
        bucket = _REQUESTS[user_id]
        while bucket and now - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return max(1, int(60 - (now - bucket[0])) + 1)
        bucket.append(now)
    return None


def reset_advisor_rate_limits_for_testing() -> None:
    with _REQUEST_LOCK:
        _REQUESTS.clear()


def conversation_view(row: AdvisorConversation) -> dict[str, object]:
    return {"id": row.id, "title": row.title, "created_at": row.created_at, "updated_at": row.updated_at}


def _response_json(value: str | None) -> dict[str, object] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def message_view(row: AdvisorMessage) -> dict[str, object]:
    return {
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "response": _response_json(row.response_json),
        "created_at": row.created_at,
    }


def create_conversation(db: Session, user: User, title: str | None = None) -> AdvisorConversation:
    title = (title or "New conversation").strip()[:120] or "New conversation"
    row = AdvisorConversation(user_id=user.id, title=title)
    db.add(row)
    db.flush()
    return row


def get_conversation(db: Session, user: User, conversation_id: int) -> AdvisorConversation:
    row = db.scalar(select(AdvisorConversation).where(AdvisorConversation.id == conversation_id, AdvisorConversation.user_id == user.id))
    if row is None:
        raise ApiError(404, "advisor_conversation_not_found", "The Advisor conversation was not found")
    return row


def list_conversations(db: Session, user: User) -> list[AdvisorConversation]:
    if not user.settings.advisor_store_history:
        return []
    return list(db.scalars(select(AdvisorConversation).where(AdvisorConversation.user_id == user.id).order_by(AdvisorConversation.updated_at.desc(), AdvisorConversation.id.desc()).limit(50)).all())


def conversation_detail(db: Session, user: User, conversation_id: int) -> dict[str, object]:
    row = get_conversation(db, user, conversation_id)
    messages = list(db.scalars(select(AdvisorMessage).where(AdvisorMessage.conversation_id == row.id, AdvisorMessage.user_id == user.id).order_by(AdvisorMessage.created_at, AdvisorMessage.id)).all())
    return {"conversation": conversation_view(row), "messages": [message_view(message) for message in messages]}


def delete_conversation(db: Session, user: User, conversation_id: int) -> None:
    row = get_conversation(db, user, conversation_id)
    db.delete(row)
    db.flush()


def delete_all_conversations(db: Session, user: User) -> None:
    db.execute(delete(AdvisorConversation).where(AdvisorConversation.user_id == user.id))
    db.flush()


def discard_private_conversation(db: Session, user_id: int, conversation_id: int) -> None:
    db.execute(delete(AdvisorConversation).where(AdvisorConversation.id == conversation_id, AdvisorConversation.user_id == user_id))
    db.flush()


def save_message(
    db: Session,
    user: User,
    conversation: AdvisorConversation,
    *,
    role: Literal["user", "assistant"],
    content: str,
    response: dict[str, object] | None = None,
    context: dict[str, object] | None = None,
) -> AdvisorMessage | None:
    if not user.settings.advisor_store_history:
        return None
    row = AdvisorMessage(
        conversation_id=conversation.id,
        user_id=user.id,
        role=role,
        content=content,
        response_json=json.dumps(response, separators=(",", ":"), default=str) if response else None,
        context_json=json.dumps(context, separators=(",", ":"), default=str) if context else None,
        created_at=utc_now(),
    )
    db.add(row)
    if conversation.title == "New conversation" and role == "user":
        conversation.title = content[:117] + ("..." if len(content) > 117 else "")
    conversation.updated_at = utc_now()
    db.flush()
    return row


def recent_history(db: Session, user: User, conversation_id: int) -> list[dict[str, str]]:
    if not user.settings.advisor_store_history:
        return []
    rows = list(db.scalars(select(AdvisorMessage).where(AdvisorMessage.conversation_id == conversation_id, AdvisorMessage.user_id == user.id).order_by(AdvisorMessage.created_at.desc(), AdvisorMessage.id.desc()).limit(12)).all())
    rows.reverse()
    return [{"role": row.role, "content": row.content[:4000]} for row in rows]


def _privacy_safe_insight(item: dict[str, object], share_merchants: bool) -> dict[str, object]:
    safe = {
        "id": item.get("id"), "signal_type": item.get("signal_type"), "category": item.get("category"),
        "priority": item.get("priority"), "score": item.get("score"), "title": item.get("title"),
        "summary": item.get("summary"), "recommendation": item.get("recommendation"), "evidence": item.get("evidence", []),
    }
    if not share_merchants and safe["signal_type"] == "recurring_price_increase":
        safe["title"] = "A recurring charge appears to have increased"
        safe["summary"] = "A detected recurring expense increased compared with its prior pattern."
    return safe



def _planning_item(item: dict[str, object], *, label: str, share_names: bool, keys: tuple[str, ...]) -> dict[str, object]:
    result = {key: item.get(key) for key in keys}
    if not share_names:
        result["name"] = f"{label} #{item.get('id')}"
    return result


def _json_safe(value: object) -> object:
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value

def sanitized_snapshot(db: Session, user: User, *, privacy_user: User | None = None) -> dict[str, object]:
    privacy = privacy_user or user
    today = datetime.now(ZoneInfo(user.settings.timezone)).date()
    month = month_budget_view(db, user, today.strftime("%Y-%m"))
    goals = list_goals(db, user)
    debts = list_debts(db, user)
    forecast = forecast_view(db, user)
    insights = list_insights(db, user, status="active")
    safe_insights = [_privacy_safe_insight(cast(dict[str, object], item), privacy.settings.advisor_share_merchants) for item in cast(list[dict[str, object]], insights["insights"])[:8]]
    snapshot = {
        "as_of": today.isoformat(),
        "currency": user.settings.currency,
        "annual_gross_income": str(user.settings.annual_gross_income) if user.settings.annual_gross_income is not None else None,
        "budget": {
            **{
                key: month[key] for key in (
                    "planned_income", "actual_income", "budgeted", "spent", "remaining", "unallocated",
                    "cash_available", "upcoming_recurring", "planning_commitments", "goal_reserves", "safe_to_spend",
                )
            },
            "month": cast(dict[str, object], month["period"])["month"],
            "categories": [
                {
                    "id": cast(dict[str, object], item["category"])["id"],
                    "name": cast(dict[str, object], item["category"])["name"],
                    "base_amount": item["base_amount"],
                    "spent_amount": item["spent_amount"],
                    "remaining_amount": item["remaining_amount"],
                    "rollover_mode": item["rollover_mode"],
                }
                for item in cast(list[dict[str, object]], month["categories"])[:40]
            ],
        },
        "goals": {
            "total_target": goals["total_target"], "total_current": goals["total_current"],
            "monthly_contributions": goals["monthly_contributions"],
            "items": [_planning_item(item, label="Goal", share_names=privacy.settings.advisor_share_planning_names, keys=("id", "name", "goal_type", "target_amount", "current_amount", "remaining_amount", "monthly_contribution", "target_date", "projected_date", "active")) for item in cast(list[dict[str, object]], goals["goals"])[:12]],
        },
        "debts": {
            "strategy": debts["strategy"], "total_balance": debts["total_balance"], "planned_monthly_payment": debts["planned_monthly_payment"],
            "interest_saved": debts["interest_saved"], "planned_debt_free_date": debts["planned_debt_free_date"],
            "items": [_planning_item(item, label="Debt", share_names=privacy.settings.advisor_share_planning_names, keys=("id", "name", "debt_type", "balance", "apr", "minimum_payment", "extra_payment", "planned_payoff_date", "interest_saved", "active")) for item in cast(list[dict[str, object]], debts["debts"])[:12]],
        },
        "forecast": {
            "cash_available": forecast["cash_available"], "goal_reserves": forecast["goal_reserves"], "spendable_cash": forecast["spendable_cash"],
            "reserve_balance": forecast["reserve_balance"], "horizons": forecast["horizons"],
        },
        "active_insights": safe_insights,
        "privacy": {
            "merchant_names_shared": privacy.settings.advisor_share_merchants,
            "transaction_descriptions_shared": privacy.settings.advisor_include_descriptions,
            "planning_names_shared": privacy.settings.advisor_share_planning_names,
        },
    }
    return cast(dict[str, object], _json_safe(snapshot))


def attached_insight(db: Session, user: User, insight_id: int | None, *, privacy_user: User | None = None) -> dict[str, object] | None:
    privacy = privacy_user or user
    if insight_id is None:
        return None
    row = db.scalar(select(InsightRecord).where(InsightRecord.id == insight_id, InsightRecord.user_id == user.id))
    if row is None:
        raise ApiError(404, "insight_not_found", "The insight was not found")
    return cast(dict[str, object], _json_safe(_privacy_safe_insight(cast(dict[str, object], insight_view(row)), privacy.settings.advisor_share_merchants)))


def _decimal_arg(value: object, *, minimum: Decimal | None = None, maximum: Decimal | None = None) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ApiError(422, "advisor_tool_arguments_invalid", "Advisor tool arguments were invalid") from None
    if minimum is not None and result < minimum or maximum is not None and result > maximum:
        raise ApiError(422, "advisor_tool_arguments_invalid", "Advisor tool arguments were invalid")
    return result


def _int_arg(value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ApiError(422, "advisor_tool_arguments_invalid", "Advisor tool arguments were invalid")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ApiError(422, "advisor_tool_arguments_invalid", "Advisor tool arguments were invalid") from None
    if result < minimum or result > maximum:
        raise ApiError(422, "advisor_tool_arguments_invalid", "Advisor tool arguments were invalid")
    return result


def _transaction_spending_amount(tx: Transaction) -> Decimal:
    kind = effective_kind(tx)
    if kind == "expense":
        return -tx.amount
    if kind == "refund":
        return -tx.amount
    return Decimal("0")


def _spending_trends_by_category(db: Session, user: User, today: date) -> dict[str, object]:
    current_start = today.replace(day=1)
    previous_month_end = current_start - timedelta(days=1)
    previous_start = previous_month_end.replace(day=1)
    comparison_day = min(today.day, previous_month_end.day)
    current_through = date(today.year, today.month, comparison_day)
    previous_through = date(previous_start.year, previous_start.month, comparison_day)

    transactions = list(
        db.scalars(
            select(Transaction)
            .options(joinedload(Transaction.category), joinedload(Transaction.user_category_override))
            .where(
                Transaction.user_id == user.id,
                Transaction.posted_date >= previous_start,
                Transaction.posted_date <= current_through,
            )
        ).all()
    )
    current_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    previous_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for tx in transactions:
        if tx.excluded_from_spending:
            continue
        category = effective_category(tx)
        category_name = category.name if category else "Uncategorized"
        amount = _transaction_spending_amount(tx)
        if amount == 0:
            continue
        if current_start <= tx.posted_date <= current_through:
            current_totals[category_name] += amount
        elif previous_start <= tx.posted_date <= previous_through:
            previous_totals[category_name] += amount

    rows: list[dict[str, object]] = []
    for category_name in sorted(set(current_totals) | set(previous_totals)):
        current_amount = current_totals[category_name]
        previous_amount = previous_totals[category_name]
        change_amount = current_amount - previous_amount
        change_percent = None
        if previous_amount > 0:
            change_percent = str(((change_amount / previous_amount) * Decimal("100")).quantize(Decimal("0.01")))
        rows.append(
            {
                "category": category_name,
                "current_amount": str(current_amount),
                "previous_amount": str(previous_amount),
                "change_amount": str(change_amount),
                "change_percent": change_percent,
                "new_spending": previous_amount == 0 and current_amount > 0,
            }
        )

    increases = sorted(
        (row for row in rows if Decimal(str(row["change_amount"])) > 0),
        key=lambda row: Decimal(str(row["change_amount"])),
        reverse=True,
    )
    decreases = sorted(
        (row for row in rows if Decimal(str(row["change_amount"])) < 0),
        key=lambda row: Decimal(str(row["change_amount"])),
    )
    return {
        "currency": user.settings.currency,
        "basis": "month_to_date_same_days",
        "current_period": {"from": current_start.isoformat(), "through": current_through.isoformat()},
        "comparison_period": {"from": previous_start.isoformat(), "through": previous_through.isoformat()},
        "categories": sorted(rows, key=lambda row: Decimal(str(row["change_amount"])), reverse=True)[:30],
        "top_increases": increases[:10],
        "top_decreases": decreases[:10],
    }


def execute_tool(db: Session, user: User, name: str, arguments: dict[str, object], *, privacy_user: User | None = None) -> dict[str, object]:
    privacy = privacy_user or user
    if name == "get_advisor_snapshot":
        return sanitized_snapshot(db, user, privacy_user=privacy)
    if name == "get_cash_forecast":
        days = _int_arg(arguments.get("days"), minimum=30, maximum=90)
        if days not in {30, 60, 90}:
            raise ApiError(422, "advisor_tool_arguments_invalid", "Forecast days must be 30, 60, or 90")
        view = forecast_view(db, user)
        horizon = next(row for row in cast(list[dict[str, object]], view["horizons"]) if row["days"] == days)
        return {"currency": view["currency"], "reserve_balance": view["reserve_balance"], "horizon": horizon}
    if name == "get_goal_projection":
        goal_id = _int_arg(arguments.get("goal_id"), minimum=1, maximum=2_147_483_647)
        goals = cast(list[dict[str, object]], list_goals(db, user)["goals"])
        goal = next((item for item in goals if item["id"] == goal_id), None)
        if goal is None:
            raise ApiError(404, "goal_not_found", "Goal was not found")
        return _planning_item(goal, label="Goal", share_names=privacy.settings.advisor_share_planning_names, keys=tuple(goal.keys()))
    if name == "get_debt_projection":
        debt_id = _int_arg(arguments.get("debt_id"), minimum=1, maximum=2_147_483_647)
        extra = _decimal_arg(arguments.get("extra_payment"), minimum=Decimal("0"), maximum=Decimal("10000000"))
        debts = list_debts(db, user)
        debt = next((item for item in cast(list[dict[str, object]], debts["debts"]) if item["id"] == debt_id), None)
        if debt is None:
            raise ApiError(404, "debt_not_found", "Debt was not found")
        scenario = scenario_view(db, user, {"extra_debt_payment": extra, "goal_contribution_adjustment": Decimal("0"), "spending_reduction": Decimal("0"), "new_monthly_expense": Decimal("0")})
        safe_debt = _planning_item(debt, label="Debt", share_names=privacy.settings.advisor_share_planning_names, keys=tuple(debt.keys()))
        return {"debt": safe_debt, "extra_payment": str(extra), "scenario_debt_free_date": scenario["scenario_debt_free_date"], "interest_saved": scenario["interest_saved"], "cash_impact_90_days": scenario["cash_impact_90_days"]}
    if name == "run_cash_scenario":
        payload = {key: _decimal_arg(arguments.get(key), minimum=Decimal("0"), maximum=Decimal("10000000")) for key in ("extra_debt_payment", "spending_reduction", "new_monthly_expense")}
        payload["goal_contribution_adjustment"] = _decimal_arg(arguments.get("goal_contribution_adjustment"), minimum=Decimal("-10000000"), maximum=Decimal("10000000"))
        return scenario_view(db, user, payload)
    if name == "evaluate_purchase":
        amount = _decimal_arg(arguments.get("amount"), minimum=Decimal("0"), maximum=Decimal("100000000"))
        month = month_budget_view(db, user, datetime.now(ZoneInfo(user.settings.timezone)).strftime("%Y-%m"))
        safe = Decimal(cast(str, month["safe_to_spend"]))
        return {"currency": user.settings.currency, "purchase_amount": str(amount), "safe_to_spend": str(safe), "remaining_safe_to_spend": str(safe - amount), "fits_current_plan": amount <= safe}
    if name == "get_spending_by_category":
        months = _int_arg(arguments.get("months"), minimum=1, maximum=12)
        today = datetime.now(ZoneInfo(user.settings.timezone)).date()
        start_month = today.month - months + 1
        year = today.year
        while start_month <= 0:
            start_month += 12; year -= 1
        start = date(year, start_month, 1)
        transactions = list(db.scalars(select(Transaction).options(joinedload(Transaction.category), joinedload(Transaction.user_category_override)).where(Transaction.user_id == user.id, Transaction.posted_date >= start, Transaction.posted_date <= today)).all())
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for tx in transactions:
            if tx.excluded_from_spending:
                continue
            category = effective_category(tx)
            key = category.name if category else "Uncategorized"
            kind = effective_kind(tx)
            if kind == "expense": totals[key] += -tx.amount
            elif kind == "refund": totals[key] -= tx.amount
        return {"currency": user.settings.currency, "months": months, "from": start.isoformat(), "through": today.isoformat(), "categories": [{"category": key, "amount": str(value)} for key, value in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:20]]}
    if name == "get_spending_trends_by_category":
        today = datetime.now(ZoneInfo(user.settings.timezone)).date()
        return _spending_trends_by_category(db, user, today)
    if name == "get_merchant_spending":
        if not privacy.settings.advisor_share_merchants:
            return {"error": "merchant_sharing_disabled"}
        months = _int_arg(arguments.get("months"), minimum=1, maximum=12)
        merchant = str(arguments.get("merchant") or "").strip()[:160]
        if not merchant:
            raise ApiError(422, "advisor_tool_arguments_invalid", "Merchant is required")
        today = datetime.now(ZoneInfo(user.settings.timezone)).date(); start = today - timedelta(days=31 * months)
        rows = list(db.scalars(select(Transaction).where(Transaction.user_id == user.id, Transaction.posted_date >= start, Transaction.posted_date <= today)).all())
        matches=[]; total=Decimal("0")
        for tx in rows:
            name_value = effective_merchant(tx) or ""
            if merchant.casefold() not in name_value.casefold(): continue
            kind=effective_kind(tx)
            if kind == "expense": total += -tx.amount
            elif kind == "refund": total -= tx.amount
            item={"date": tx.posted_date.isoformat(), "merchant": name_value, "amount": str(tx.amount), "kind": kind}
            if privacy.settings.advisor_include_descriptions: item["description"] = tx.description[:255]
            matches.append(item)
        return {"currency": user.settings.currency, "merchant": merchant, "months": months, "total_spending": str(total), "transactions": matches[-25:]}
    if name == "get_recurring_summary":
        streams = list(db.scalars(select(RecurringStream).where(RecurringStream.user_id == user.id, RecurringStream.active.is_(True))).all())
        factors={"weekly":Decimal("52")/12,"biweekly":Decimal("26")/12,"monthly":Decimal("1"),"quarterly":Decimal("1")/3,"annual":Decimal("1")/12}
        expenses=[stream for stream in streams if stream.kind == "expense"]
        monthly=sum((stream.average_amount*factors.get(stream.cadence,Decimal("0")) for stream in expenses),Decimal("0"))
        result: dict[str, object]={"currency":user.settings.currency,"monthly_estimate":str(monthly),"annualized":str(monthly*12),"stream_count":len(expenses)}
        if privacy.settings.advisor_share_merchants:
            result["largest"]=[{"name":stream.display_name,"cadence":stream.cadence,"average_amount":str(stream.average_amount)} for stream in sorted(expenses,key=lambda x:x.average_amount,reverse=True)[:10]]
        return result
    if name == "get_active_insights":
        items=cast(list[dict[str,object]], list_insights(db,user,status="active")["insights"])
        return {"insights":[_privacy_safe_insight(item,privacy.settings.advisor_share_merchants) for item in items[:12]]}
    raise ApiError(422, "advisor_tool_not_allowed", "The requested Advisor tool is not allowed")


TOOL_DEFINITIONS: list[dict[str, object]] = [
    {"type":"function","name":"get_advisor_snapshot","description":"Return Budget's sanitized current financial snapshot.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"get_cash_forecast","description":"Return one deterministic cash forecast horizon.","parameters":{"type":"object","properties":{"days":{"type":"integer","enum":[30,60,90]}},"required":["days"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"get_goal_projection","description":"Return Budget's projection for one financial goal by id.","parameters":{"type":"object","properties":{"goal_id":{"type":"integer","minimum":1}},"required":["goal_id"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"get_debt_projection","description":"Evaluate an additional monthly debt payment for one debt.","parameters":{"type":"object","properties":{"debt_id":{"type":"integer","minimum":1},"extra_payment":{"type":"number","minimum":0}},"required":["debt_id","extra_payment"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"run_cash_scenario","description":"Run Budget's read-only 90-day cash/debt scenario engine.","parameters":{"type":"object","properties":{"extra_debt_payment":{"type":"number","minimum":0},"goal_contribution_adjustment":{"type":"number"},"spending_reduction":{"type":"number","minimum":0},"new_monthly_expense":{"type":"number","minimum":0}},"required":["extra_debt_payment","goal_contribution_adjustment","spending_reduction","new_monthly_expense"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"evaluate_purchase","description":"Compare a proposed one-time purchase with deterministic safe-to-spend.","parameters":{"type":"object","properties":{"amount":{"type":"number","minimum":0}},"required":["amount"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"get_spending_by_category","description":"Summarize spending by category over a bounded number of months.","parameters":{"type":"object","properties":{"months":{"type":"integer","minimum":1,"maximum":12}},"required":["months"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"get_spending_trends_by_category","description":"Compare current month-to-date category spending with the same number of days in the prior month. Use for questions about which categories increased or decreased.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"get_merchant_spending","description":"Summarize a merchant only when the user explicitly enabled merchant-name sharing.","parameters":{"type":"object","properties":{"merchant":{"type":"string","maxLength":160},"months":{"type":"integer","minimum":1,"maximum":12}},"required":["merchant","months"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"get_recurring_summary","description":"Return cadence-normalized recurring expense totals.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
    {"type":"function","name":"get_active_insights","description":"Return active deterministic Budget insights.","parameters":{"type":"object","properties":{},"additionalProperties":False},"strict":True},
]


def trusted_facts(snapshot: dict[str, object], tool_results: list[dict[str, object]]) -> list[dict[str, str]]:
    currency = str(snapshot.get("currency", "USD"))
    budget = cast(dict[str, object], snapshot.get("budget") or {})
    facts=[{"label":"Safe to spend","value":f"{currency} {budget.get('safe_to_spend','0')}","detail":"Calculated by Budget"},{"label":"Cash available","value":f"{currency} {budget.get('cash_available','0')}","detail":"Depository cash"}]
    for result in tool_results:
        name=str(result.get("name")); data=cast(dict[str,object],result.get("result") or {})
        if name=="evaluate_purchase": facts.append({"label":"After purchase","value":f"{currency} {data.get('remaining_safe_to_spend','0')}","detail":"Safe-to-spend after proposed purchase"})
        elif name=="get_spending_trends_by_category":
            top = cast(list[dict[str, object]], data.get("top_increases") or [])
            if top:
                row = top[0]
                percent = row.get("change_percent")
                detail = f"{percent}% vs prior month-to-date" if percent is not None else "New spending vs prior month-to-date"
                facts.append({"label":"Top spending increase","value":f"{row.get('category','Uncategorized')} +{currency} {row.get('change_amount','0')}","detail":detail})
        elif name=="get_recurring_summary": facts.append({"label":"Recurring / year","value":f"{currency} {data.get('annualized','0')}","detail":"Cadence-normalized estimate"})
        elif name=="run_cash_scenario": facts.append({"label":"90-day scenario impact","value":f"{currency} {data.get('cash_impact_90_days','0')}","detail":"Compared with baseline"})
        elif name=="get_debt_projection": facts.append({"label":"Projected interest saved","value":f"{currency} {data.get('interest_saved','0')}","detail":"Budget debt simulation"})
    return facts[:6]
