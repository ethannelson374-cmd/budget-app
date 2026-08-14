from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import as_utc, utc_now
from app.models import (
    AdvisorProposal,
    AdvisorProposalAction,
    AdvisorProposalExecution,
    Category,
    Debt,
    DebtStrategySettings,
    FinancialGoal,
    ForecastAssumptions,
    MonthlyBudget,
    MonthlyBudgetCategory,
    User,
)
from app.services.budget_planning import month_budget_view, put_monthly_budget
from app.services.financial_planning import (
    forecast_view,
    list_debts,
    list_goals,
    update_debt,
    update_debt_strategy,
    update_forecast_assumptions,
    update_goal,
)

ACTION_TYPES = {
    "budget_category_monthly_set",
    "goal_monthly_contribution_set",
    "debt_extra_payment_set",
    "debt_strategy_set",
    "forecast_reserve_set",
}
MAX_PROPOSAL_ACTIONS = 6
PROPOSAL_TTL = timedelta(hours=24)
MONEY_LIMIT = Decimal("100000000")


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def _load_json(value: str | None, fallback: object) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _money(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ApiError(422, "advisor_proposal_invalid", "The proposed financial amount was invalid") from None
    if not result.is_finite() or result < 0 or result > MONEY_LIMIT:
        raise ApiError(422, "advisor_proposal_invalid", "The proposed financial amount was outside the allowed range")
    return result.quantize(Decimal("0.0001"))


def _month(value: str, *, expected: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except ValueError:
        raise ApiError(422, "advisor_proposal_invalid", "The proposed budget month was invalid") from None
    normalized = parsed.strftime("%Y-%m")
    if normalized != expected:
        raise ApiError(
            422,
            "advisor_proposal_invalid",
            "Advisor budget actions may only change the current budget month",
        )
    return normalized


def _bool_text(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ApiError(422, "advisor_proposal_invalid", "The proposed reserve setting was invalid")


def _monthly_raw_state(db: Session, user: User, month: str) -> dict[str, object]:
    month_start = datetime.strptime(month, "%Y-%m").date().replace(day=1)
    budget = db.scalar(
        select(MonthlyBudget).where(MonthlyBudget.user_id == user.id, MonthlyBudget.month == month_start)
    )
    if budget is None:
        return {"exists": False}
    rows = list(
        db.scalars(
            select(MonthlyBudgetCategory)
            .where(
                MonthlyBudgetCategory.user_id == user.id,
                MonthlyBudgetCategory.budget_id == budget.id,
            )
            .order_by(MonthlyBudgetCategory.category_id)
        ).all()
    )
    return {
        "exists": True,
        "mode": budget.mode,
        "planned_income": str(budget.planned_income) if budget.planned_income is not None else None,
        "notes": budget.notes,
        "categories": [
            {
                "category_id": row.category_id,
                "planned_amount": str(row.planned_amount),
                "rollover_mode": row.rollover_mode,
            }
            for row in rows
        ],
    }


def _set_monthly_category(
    db: Session, user: User, month: str, category_id: int, amount: Decimal
) -> None:
    month_start = datetime.strptime(month, "%Y-%m").date().replace(day=1)
    existing = db.scalar(
        select(MonthlyBudget).where(MonthlyBudget.user_id == user.id, MonthlyBudget.month == month_start)
    )
    current = month_budget_view(db, user, month)
    if existing is None:
        mode = "override" if current["has_annual_plan"] else "standalone"
        planned_income: Decimal | None = None if mode == "override" else Decimal(cast(str, current["planned_income"]))
        notes = None
        categories: list[dict[str, object]] = []
        if mode == "standalone":
            categories = [
                {
                    "category_id": int(cast(dict[str, object], row["category"])["id"]),
                    "planned_amount": Decimal(cast(str, row["base_amount"])),
                    "rollover_mode": str(row["rollover_mode"]),
                }
                for row in cast(list[dict[str, object]], current["categories"])
            ]
    else:
        mode = existing.mode
        planned_income = existing.planned_income
        notes = existing.notes
        explicit = list(
            db.scalars(
                select(MonthlyBudgetCategory).where(
                    MonthlyBudgetCategory.user_id == user.id,
                    MonthlyBudgetCategory.budget_id == existing.id,
                )
            ).all()
        )
        categories = [
            {
                "category_id": row.category_id,
                "planned_amount": row.planned_amount,
                "rollover_mode": row.rollover_mode,
            }
            for row in explicit
        ]

    replaced = False
    for row in categories:
        if int(row["category_id"]) == category_id:
            row["planned_amount"] = amount
            replaced = True
            break
    if not replaced:
        effective = next(
            (
                item
                for item in cast(list[dict[str, object]], current["categories"])
                if int(cast(dict[str, object], item["category"])["id"]) == category_id
            ),
            None,
        )
        categories.append(
            {
                "category_id": category_id,
                "planned_amount": amount,
                "rollover_mode": str(effective["rollover_mode"]) if effective else "off",
            }
        )

    put_monthly_budget(
        db,
        user,
        month,
        {
            "mode": mode,
            "planned_income": planned_income,
            "notes": notes,
            "categories": categories,
        },
    )


def _restore_monthly_state(db: Session, user: User, month: str, state: dict[str, object]) -> None:
    month_start = datetime.strptime(month, "%Y-%m").date().replace(day=1)
    if not state.get("exists"):
        budget = db.scalar(
            select(MonthlyBudget).where(MonthlyBudget.user_id == user.id, MonthlyBudget.month == month_start)
        )
        if budget is not None:
            db.delete(budget)
            db.flush()
        return
    put_monthly_budget(
        db,
        user,
        month,
        {
            "mode": state["mode"],
            "planned_income": state.get("planned_income"),
            "notes": state.get("notes"),
            "categories": cast(list[dict[str, object]], state.get("categories") or []),
        },
    )


def _impact_snapshot(db: Session, user: User, month: str) -> dict[str, object]:
    budget = month_budget_view(db, user, month)
    goals = list_goals(db, user)
    debts = list_debts(db, user)
    forecast = forecast_view(db, user)
    horizons = cast(list[dict[str, object]], forecast["horizons"])
    ninety = next((row for row in horizons if int(row["days"]) == 90), horizons[-1] if horizons else None)
    return {
        "safe_to_spend": budget["safe_to_spend"],
        "monthly_goal_contributions": goals["monthly_contributions"],
        "planned_monthly_debt": debts["planned_monthly_payment"],
        "planned_debt_free_date": debts["planned_debt_free_date"],
        "interest_saved": debts["interest_saved"],
        "reserve_balance": forecast["reserve_balance"],
        "projected_balance_90_days": ninety["projected_balance"] if ninety else "0.0000",
    }


def _metric_value(currency: str, key: str, value: object) -> str:
    if key in {
        "safe_to_spend",
        "monthly_goal_contributions",
        "planned_monthly_debt",
        "interest_saved",
        "reserve_balance",
        "projected_balance_90_days",
    }:
        return f"{currency} {value}"
    return str(value) if value is not None else "—"


METRIC_LABELS = {
    "safe_to_spend": "Safe to spend",
    "monthly_goal_contributions": "Monthly goal contributions",
    "planned_monthly_debt": "Planned monthly debt",
    "planned_debt_free_date": "Projected debt-free date",
    "interest_saved": "Projected interest saved",
    "reserve_balance": "Cash reserve target",
    "projected_balance_90_days": "90-day projected balance",
}


def _preview(currency: str, before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    impacts: list[dict[str, str]] = []
    for key, label in METRIC_LABELS.items():
        old = before.get(key)
        new = after.get(key)
        if old == new and key != "safe_to_spend":
            continue
        impacts.append(
            {
                "label": label,
                "before": _metric_value(currency, key, old),
                "after": _metric_value(currency, key, new),
            }
        )
    return {"impacts": impacts[:7]}


def _normalize_actions(
    db: Session,
    user: User,
    suggestions: list[dict[str, object]],
    *,
    current_month: str,
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, int | None, str]] = set()
    for raw in suggestions[:MAX_PROPOSAL_ACTIONS]:
        action_type = str(raw.get("action_type") or "")
        if action_type not in ACTION_TYPES:
            continue
        target_raw = raw.get("target_id", 0)
        try:
            target_id = int(target_raw)
        except (TypeError, ValueError):
            continue
        value = str(raw.get("value") or "").strip()
        secondary = str(raw.get("secondary_value") or "").strip()
        rationale = str(raw.get("rationale") or "").strip()[:500] or "Recommended by Ask Budget."

        if action_type == "budget_category_monthly_set":
            month = _month(secondary, expected=current_month)
            category = db.scalar(
                select(Category).where(Category.id == target_id, Category.user_id == user.id, Category.enabled.is_(True))
            )
            if category is None:
                continue
            amount = _money(value)
            current = month_budget_view(db, user, month)
            current_row = next(
                (
                    row
                    for row in cast(list[dict[str, object]], current["categories"])
                    if int(cast(dict[str, object], row["category"])["id"]) == target_id
                ),
                None,
            )
            before_amount = Decimal(str(current_row["base_amount"])) if current_row else Decimal("0")
            item = {
                "action_type": action_type,
                "target_id": target_id,
                "payload": {"month": month, "amount": str(amount)},
                "label": f"Set {category.name} budget",
                "rationale": rationale,
                "before": {"amount": str(before_amount)},
                "after": {"amount": str(amount)},
            }
            unique = (action_type, target_id, month)
        elif action_type == "goal_monthly_contribution_set":
            goal = db.scalar(select(FinancialGoal).where(FinancialGoal.id == target_id, FinancialGoal.user_id == user.id))
            if goal is None:
                continue
            amount = _money(value)
            item = {
                "action_type": action_type,
                "target_id": target_id,
                "payload": {"amount": str(amount)},
                "label": f"Set {goal.name} monthly contribution",
                "rationale": rationale,
                "before": {"amount": str(goal.monthly_contribution)},
                "after": {"amount": str(amount)},
            }
            unique = (action_type, target_id, "")
        elif action_type == "debt_extra_payment_set":
            debt = db.scalar(select(Debt).where(Debt.id == target_id, Debt.user_id == user.id))
            if debt is None:
                continue
            amount = _money(value)
            item = {
                "action_type": action_type,
                "target_id": target_id,
                "payload": {"amount": str(amount)},
                "label": f"Set {debt.name} extra payment",
                "rationale": rationale,
                "before": {"amount": str(debt.extra_payment)},
                "after": {"amount": str(amount)},
            }
            unique = (action_type, target_id, "")
        elif action_type == "debt_strategy_set":
            if value not in {"avalanche", "snowball", "custom"}:
                continue
            extra = _money(secondary or "0")
            settings = db.get(DebtStrategySettings, user.id)
            current_strategy = settings.strategy if settings else "avalanche"
            current_extra = settings.monthly_extra_budget if settings else Decimal("0")
            item = {
                "action_type": action_type,
                "target_id": None,
                "payload": {"strategy": value, "monthly_extra_budget": str(extra)},
                "label": "Update debt payoff strategy",
                "rationale": rationale,
                "before": {"strategy": current_strategy, "monthly_extra_budget": str(current_extra)},
                "after": {"strategy": value, "monthly_extra_budget": str(extra)},
            }
            unique = (action_type, None, "")
        else:
            reserve = _money(value)
            include = _bool_text(secondary or "true")
            settings = db.get(ForecastAssumptions, user.id)
            current_reserve = settings.reserve_balance if settings else Decimal("0")
            current_include = settings.include_budget_reserve if settings else True
            item = {
                "action_type": action_type,
                "target_id": None,
                "payload": {"reserve_balance": str(reserve), "include_budget_reserve": include},
                "label": "Update forecast reserve target",
                "rationale": rationale,
                "before": {"reserve_balance": str(current_reserve), "include_budget_reserve": current_include},
                "after": {"reserve_balance": str(reserve), "include_budget_reserve": include},
            }
            unique = (action_type, None, "")
        if unique in seen:
            continue
        seen.add(unique)
        normalized.append(item)
    return normalized


def _resource_state(db: Session, user: User, actions: list[dict[str, object]]) -> dict[str, object]:
    state: dict[str, object] = {
        "monthly_budgets": {},
        "goals": {},
        "debts": {},
        "debt_strategy": None,
        "forecast": None,
    }
    budget_targets: dict[str, set[int]] = {}
    for action in actions:
        action_type = str(action["action_type"])
        target_id = action.get("target_id")
        payload = cast(dict[str, object], action["payload"])
        if action_type == "budget_category_monthly_set":
            month = str(payload["month"])
            budget_targets.setdefault(month, set()).add(int(target_id))
        elif action_type == "goal_monthly_contribution_set":
            goal = db.scalar(select(FinancialGoal).where(FinancialGoal.id == int(target_id), FinancialGoal.user_id == user.id))
            if goal is None:
                raise ApiError(409, "advisor_proposal_stale", "A goal used by this plan no longer exists")
            cast(dict[str, object], state["goals"])[str(goal.id)] = {"monthly_contribution": str(goal.monthly_contribution)}
        elif action_type == "debt_extra_payment_set":
            debt = db.scalar(select(Debt).where(Debt.id == int(target_id), Debt.user_id == user.id))
            if debt is None:
                raise ApiError(409, "advisor_proposal_stale", "A debt used by this plan no longer exists")
            cast(dict[str, object], state["debts"])[str(debt.id)] = {"extra_payment": str(debt.extra_payment)}
        elif action_type == "debt_strategy_set":
            settings = db.get(DebtStrategySettings, user.id)
            state["debt_strategy"] = {
                "exists": settings is not None,
                "strategy": settings.strategy if settings else "avalanche",
                "monthly_extra_budget": str(settings.monthly_extra_budget if settings else Decimal("0")),
            }
        elif action_type == "forecast_reserve_set":
            settings = db.get(ForecastAssumptions, user.id)
            state["forecast"] = {
                "exists": settings is not None,
                "reserve_balance": str(settings.reserve_balance if settings else Decimal("0")),
                "include_budget_reserve": settings.include_budget_reserve if settings else True,
            }

    monthly = cast(dict[str, object], state["monthly_budgets"])
    for month, category_ids in budget_targets.items():
        view = month_budget_view(db, user, month)
        effective = {
            str(int(cast(dict[str, object], row["category"])["id"])): str(row["base_amount"])
            for row in cast(list[dict[str, object]], view["categories"])
            if int(cast(dict[str, object], row["category"])["id"]) in category_ids
        }
        for category_id in category_ids:
            effective.setdefault(str(category_id), "0.0000")
        monthly[month] = {"raw": _monthly_raw_state(db, user, month), "effective": effective}
    return state


def _apply_actions(db: Session, user: User, actions: list[dict[str, object]]) -> None:
    for action in actions:
        action_type = str(action["action_type"])
        target_id = action.get("target_id")
        payload = cast(dict[str, object], action["payload"])
        if action_type == "budget_category_monthly_set":
            _set_monthly_category(db, user, str(payload["month"]), int(target_id), Decimal(str(payload["amount"])))
        elif action_type == "goal_monthly_contribution_set":
            update_goal(db, user, int(target_id), {"monthly_contribution": Decimal(str(payload["amount"]))})
        elif action_type == "debt_extra_payment_set":
            update_debt(db, user, int(target_id), {"extra_payment": Decimal(str(payload["amount"]))})
        elif action_type == "debt_strategy_set":
            update_debt_strategy(db, user, str(payload["strategy"]), Decimal(str(payload["monthly_extra_budget"])))
        elif action_type == "forecast_reserve_set":
            update_forecast_assumptions(
                db,
                user,
                Decimal(str(payload["reserve_balance"])),
                bool(payload["include_budget_reserve"]),
            )
    db.flush()


def _restore_resources(db: Session, user: User, rollback: dict[str, object]) -> None:
    monthly = cast(dict[str, dict[str, object]], rollback.get("monthly_budgets") or {})
    for month, value in monthly.items():
        _restore_monthly_state(db, user, month, cast(dict[str, object], value.get("raw") or {"exists": False}))

    for goal_id, value in cast(dict[str, dict[str, object]], rollback.get("goals") or {}).items():
        update_goal(db, user, int(goal_id), {"monthly_contribution": Decimal(str(value["monthly_contribution"]))})
    for debt_id, value in cast(dict[str, dict[str, object]], rollback.get("debts") or {}).items():
        update_debt(db, user, int(debt_id), {"extra_payment": Decimal(str(value["extra_payment"]))})

    strategy = rollback.get("debt_strategy")
    if isinstance(strategy, dict):
        if strategy.get("exists"):
            update_debt_strategy(
                db,
                user,
                str(strategy["strategy"]),
                Decimal(str(strategy["monthly_extra_budget"])),
            )
        else:
            db.execute(delete(DebtStrategySettings).where(DebtStrategySettings.user_id == user.id))

    forecast = rollback.get("forecast")
    if isinstance(forecast, dict):
        if forecast.get("exists"):
            update_forecast_assumptions(
                db,
                user,
                Decimal(str(forecast["reserve_balance"])),
                bool(forecast["include_budget_reserve"]),
            )
        else:
            db.execute(delete(ForecastAssumptions).where(ForecastAssumptions.user_id == user.id))
    db.flush()


def _proposal_actions(db: Session, proposal: AdvisorProposal) -> list[AdvisorProposalAction]:
    return list(
        db.scalars(
            select(AdvisorProposalAction)
            .where(
                AdvisorProposalAction.proposal_id == proposal.id,
                AdvisorProposalAction.user_id == proposal.user_id,
            )
            .order_by(AdvisorProposalAction.sort_order, AdvisorProposalAction.id)
        ).all()
    )


def _normalized_from_rows(rows: list[AdvisorProposalAction]) -> list[dict[str, object]]:
    return [
        {
            "action_type": row.action_type,
            "target_id": row.target_id,
            "payload": cast(dict[str, object], _load_json(row.payload_json, {})),
            "label": row.label,
            "rationale": row.rationale,
            "before": cast(dict[str, object], _load_json(row.before_json, {})),
            "after": cast(dict[str, object], _load_json(row.after_json, {})),
        }
        for row in rows
    ]


def create_proposal(
    db: Session,
    user: User,
    *,
    conversation_id: int,
    title: str,
    summary: str,
    suggestions: list[dict[str, object]],
) -> AdvisorProposal | None:
    if not user.settings.advisor_store_history:
        return None
    user_id = user.id
    today = datetime.now(ZoneInfo(user.settings.timezone)).date()
    current_month = today.strftime("%Y-%m")
    normalized = _normalize_actions(db, user, suggestions, current_month=current_month)
    if not normalized:
        return None

    before_state = _resource_state(db, user, normalized)
    before_impact = _impact_snapshot(db, user, current_month)
    try:
        _apply_actions(db, user, normalized)
        after_impact = _impact_snapshot(db, user, current_month)
    except Exception:
        db.rollback()
        raise
    db.rollback()

    user = db.get(User, user_id)
    if user is None:
        return None
    proposal = AdvisorProposal(
        user_id=user.id,
        conversation_id=conversation_id,
        status="draft",
        title=(title.strip()[:180] or "Recommended financial plan"),
        summary=(summary.strip()[:2000] or "Review these changes before applying them."),
        currency=user.settings.currency,
        preview_json=_json(_preview(user.settings.currency, before_impact, after_impact)),
        precondition_json=_json(before_state),
        rollback_json=_json(before_state),
        applied_state_json=None,
        expires_at=utc_now() + PROPOSAL_TTL,
    )
    db.add(proposal)
    db.flush()
    for index, item in enumerate(normalized, start=1):
        db.add(
            AdvisorProposalAction(
                proposal_id=proposal.id,
                user_id=user.id,
                sort_order=index,
                action_type=str(item["action_type"]),
                target_id=cast(int | None, item.get("target_id")),
                label=str(item["label"]),
                rationale=str(item["rationale"]),
                payload_json=_json(item["payload"]),
                before_json=_json(item["before"]),
                after_json=_json(item["after"]),
            )
        )
    db.flush()
    return proposal


def get_proposal(db: Session, user: User, proposal_id: int) -> AdvisorProposal:
    proposal = db.scalar(
        select(AdvisorProposal).where(AdvisorProposal.id == proposal_id, AdvisorProposal.user_id == user.id)
    )
    if proposal is None:
        raise ApiError(404, "advisor_proposal_not_found", "The Advisor action plan was not found")
    return proposal


def proposal_view(db: Session, user: User, proposal: AdvisorProposal) -> dict[str, object]:
    rows = _proposal_actions(db, proposal)
    status = proposal.status
    if status == "draft" and as_utc(proposal.expires_at) <= utc_now():
        status = "expired"
    return {
        "id": proposal.id,
        "conversation_id": proposal.conversation_id,
        "status": status,
        "title": proposal.title,
        "summary": proposal.summary,
        "currency": proposal.currency,
        "preview": cast(dict[str, object], _load_json(proposal.preview_json, {"impacts": []})),
        "actions": [
            {
                "id": row.id,
                "action_type": row.action_type,
                "label": row.label,
                "rationale": row.rationale,
                "before": cast(dict[str, object], _load_json(row.before_json, {})),
                "after": cast(dict[str, object], _load_json(row.after_json, {})),
            }
            for row in rows
        ],
        "created_at": proposal.created_at,
        "expires_at": proposal.expires_at,
        "applied_at": proposal.applied_at,
        "rejected_at": proposal.rejected_at,
        "undone_at": proposal.undone_at,
    }


def apply_proposal(db: Session, user: User, proposal_id: int) -> AdvisorProposal:
    proposal = get_proposal(db, user, proposal_id)
    if proposal.status != "draft":
        raise ApiError(409, "advisor_proposal_not_draft", "This action plan can no longer be applied")
    if as_utc(proposal.expires_at) <= utc_now():
        proposal.status = "expired"
        db.flush()
        raise ApiError(409, "advisor_proposal_expired", "This action plan has expired; ask Budget to build a fresh plan")
    rows = _proposal_actions(db, proposal)
    actions = _normalized_from_rows(rows)
    expected = cast(dict[str, object], _load_json(proposal.precondition_json, {}))
    current = _resource_state(db, user, actions)
    if _json(current) != _json(expected):
        raise ApiError(
            409,
            "advisor_proposal_stale",
            "Your financial plan changed after this recommendation was created; review a fresh plan before applying changes",
        )
    _apply_actions(db, user, actions)
    proposal.applied_state_json = _json(_resource_state(db, user, actions))
    proposal.status = "applied"
    proposal.applied_at = utc_now()
    db.add(
        AdvisorProposalExecution(
            proposal_id=proposal.id,
            user_id=user.id,
            operation="apply",
            outcome="success",
            detail_json=_json({"action_count": len(actions)}),
            created_at=utc_now(),
        )
    )
    db.flush()
    return proposal


def reject_proposal(db: Session, user: User, proposal_id: int) -> AdvisorProposal:
    proposal = get_proposal(db, user, proposal_id)
    if proposal.status != "draft":
        raise ApiError(409, "advisor_proposal_not_draft", "This action plan can no longer be dismissed")
    proposal.status = "rejected"
    proposal.rejected_at = utc_now()
    db.flush()
    return proposal


def undo_proposal(db: Session, user: User, proposal_id: int) -> AdvisorProposal:
    proposal = get_proposal(db, user, proposal_id)
    if proposal.status != "applied":
        raise ApiError(409, "advisor_proposal_not_applied", "Only an applied action plan can be undone")
    rows = _proposal_actions(db, proposal)
    actions = _normalized_from_rows(rows)
    expected = cast(dict[str, object], _load_json(proposal.applied_state_json, {}))
    current = _resource_state(db, user, actions)
    if _json(current) != _json(expected):
        raise ApiError(
            409,
            "advisor_proposal_changed_since_apply",
            "One of these settings changed after the plan was applied, so Budget will not overwrite the newer values",
        )
    rollback = cast(dict[str, object], _load_json(proposal.rollback_json, {}))
    _restore_resources(db, user, rollback)
    proposal.status = "undone"
    proposal.undone_at = utc_now()
    db.add(
        AdvisorProposalExecution(
            proposal_id=proposal.id,
            user_id=user.id,
            operation="undo",
            outcome="success",
            detail_json=_json({"action_count": len(actions)}),
            created_at=utc_now(),
        )
    )
    db.flush()
    return proposal
