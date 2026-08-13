from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ApiError
from app.core.security import utc_now
from app.models import (
    Account,
    Debt,
    DebtStrategySettings,
    FinancialGoal,
    ForecastAssumptions,
    GoalContribution,
    RecurringStream,
    User,
)
from app.services.budget_planning import month_budget_view
from app.services.views import account_view, money

Q = Decimal("0.0001")
CADENCE_DAYS = {
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
    "quarterly": 91,
    "annual": 365,
}


def _q(value: Decimal) -> Decimal:
    return value.quantize(Q, rounding=ROUND_HALF_UP)


def _today(user: User) -> date:
    return datetime.now(ZoneInfo(user.settings.timezone)).date()


def _owned_account(
    db: Session,
    user: User,
    account_id: int | None,
    *,
    allowed_types: set[str] | None = None,
) -> Account | None:
    if account_id is None:
        return None
    account = db.scalar(
        select(Account).where(Account.id == account_id, Account.user_id == user.id)
    )
    if account is None:
        raise ApiError(422, "invalid_linked_account", "Linked account was not found")
    if account.currency != user.settings.currency:
        raise ApiError(
            422,
            "linked_account_currency_mismatch",
            "Linked account must use your budget currency",
        )
    if allowed_types is not None and account.account_type not in allowed_types:
        raise ApiError(
            422,
            "invalid_linked_account_type",
            "Linked account type is not valid for this planning item",
        )
    return account


def _goal_current(goal: FinancialGoal) -> Decimal:
    if goal.linked_account is not None:
        return _q(max(goal.linked_account.current_balance, Decimal("0")))
    return _q(goal.current_amount)


def _goal_projected_date(goal: FinancialGoal, current: Decimal, today: date) -> date | None:
    remaining = max(goal.target_amount - current, Decimal("0"))
    if remaining <= 0:
        return today
    if goal.monthly_contribution <= 0:
        return None
    months = int((remaining / goal.monthly_contribution).to_integral_value(rounding=ROUND_CEILING))
    year = today.year + (today.month - 1 + months) // 12
    month = (today.month - 1 + months) % 12 + 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def _ensure_goal_account_available(
    db: Session, user: User, account: Account | None, *, exclude_goal_id: int | None = None
) -> None:
    if account is None:
        return
    statement = select(FinancialGoal.id).where(
        FinancialGoal.user_id == user.id, FinancialGoal.linked_account_id == account.id
    )
    if exclude_goal_id is not None:
        statement = statement.where(FinancialGoal.id != exclude_goal_id)
    if db.scalar(statement) is not None:
        raise ApiError(
            422,
            "goal_account_already_linked",
            "That account is already linked to another financial goal",
        )


def _linked_goal_reserve(goals: list[FinancialGoal]) -> Decimal:
    return _q(
        sum(
            (
                min(_goal_current(goal), goal.target_amount)
                for goal in goals
                if goal.linked_account is not None
            ),
            Decimal("0"),
        )
    )


def _goal_view(goal: FinancialGoal, user: User) -> dict[str, object]:
    current = _goal_current(goal)
    remaining = _q(max(goal.target_amount - current, Decimal("0")))
    progress = _q(min(current / goal.target_amount * Decimal("100"), Decimal("100")))
    today = _today(user)
    return {
        "id": goal.id,
        "name": goal.name,
        "goal_type": goal.goal_type,
        "target_amount": money(goal.target_amount),
        "current_amount": money(current),
        "remaining_amount": money(remaining),
        "monthly_contribution": money(goal.monthly_contribution),
        "progress_pct": money(progress),
        "target_date": goal.target_date,
        "projected_date": _goal_projected_date(goal, current, today),
        "priority": goal.priority,
        "active": goal.active,
        "notes": goal.notes,
        "linked_account": account_view(goal.linked_account) if goal.linked_account else None,
    }


def list_goals(db: Session, user: User) -> dict[str, object]:
    goals = list(
        db.scalars(
            select(FinancialGoal)
            .options(joinedload(FinancialGoal.linked_account).joinedload(Account.institution))
            .where(FinancialGoal.user_id == user.id)
            .order_by(FinancialGoal.active.desc(), FinancialGoal.priority, FinancialGoal.id)
        ).all()
    )
    active = [goal for goal in goals if goal.active]
    total_target = sum((goal.target_amount for goal in active), Decimal("0"))
    total_current = sum(
        (min(_goal_current(goal), goal.target_amount) for goal in active), Decimal("0")
    )
    monthly = sum(
        (goal.monthly_contribution for goal in active if _goal_current(goal) < goal.target_amount),
        Decimal("0"),
    )
    return {
        "currency": user.settings.currency,
        "total_target": money(_q(total_target)),
        "total_current": money(_q(total_current)),
        "monthly_contributions": money(_q(monthly)),
        "goals": [_goal_view(goal, user) for goal in goals],
    }


def create_goal(db: Session, user: User, payload: dict[str, Any]) -> FinancialGoal:
    account = _owned_account(
        db, user, payload.get("linked_account_id"), allowed_types={"depository", "investment"}
    )
    _ensure_goal_account_available(db, user, account)
    goal = FinancialGoal(
        user_id=user.id,
        linked_account_id=account.id if account else None,
        name=str(payload["name"]).strip(),
        goal_type=str(payload["goal_type"]),
        target_amount=_q(Decimal(payload["target_amount"])),
        current_amount=_q(Decimal(payload["current_amount"])),
        monthly_contribution=_q(Decimal(payload["monthly_contribution"])),
        target_date=payload.get("target_date"),
        priority=int(payload["priority"]),
        active=bool(payload["active"]),
        notes=payload.get("notes"),
    )
    db.add(goal)
    db.flush()
    return goal


def update_goal(db: Session, user: User, goal_id: int, payload: dict[str, Any]) -> FinancialGoal:
    goal = db.scalar(
        select(FinancialGoal).where(FinancialGoal.id == goal_id, FinancialGoal.user_id == user.id)
    )
    if goal is None:
        raise ApiError(404, "goal_not_found", "Goal was not found")
    if "linked_account_id" in payload:
        account = _owned_account(
            db, user, payload["linked_account_id"], allowed_types={"depository", "investment"}
        )
        _ensure_goal_account_available(db, user, account, exclude_goal_id=goal.id)
        goal.linked_account_id = account.id if account else None
    for field in ("name", "goal_type", "priority", "active"):
        if field in payload:
            value = payload[field]
            if value is None:
                raise ApiError(422, "invalid_goal", f"{field} may not be null")
            setattr(goal, field, value.strip() if field == "name" else value)
    for field in ("target_date", "notes"):
        if field in payload:
            setattr(goal, field, payload[field])
    for field in ("target_amount", "current_amount", "monthly_contribution"):
        if field in payload:
            value = payload[field]
            if value is None:
                raise ApiError(422, "invalid_goal", f"{field} may not be null")
            setattr(goal, field, _q(Decimal(value)))
    db.flush()
    return goal


def delete_goal(db: Session, user: User, goal_id: int) -> None:
    goal = db.scalar(
        select(FinancialGoal).where(FinancialGoal.id == goal_id, FinancialGoal.user_id == user.id)
    )
    if goal is None:
        raise ApiError(404, "goal_not_found", "Goal was not found")
    db.delete(goal)
    db.flush()


def add_goal_contribution(
    db: Session,
    user: User,
    goal_id: int,
    amount: Decimal,
    contribution_date: date,
    notes: str | None,
) -> FinancialGoal:
    goal = db.scalar(
        select(FinancialGoal).where(FinancialGoal.id == goal_id, FinancialGoal.user_id == user.id)
    )
    if goal is None:
        raise ApiError(404, "goal_not_found", "Goal was not found")
    if goal.linked_account_id is not None:
        raise ApiError(
            422,
            "linked_goal_tracks_account",
            "This goal tracks its linked account balance automatically",
        )
    value = _q(amount)
    goal.current_amount = _q(max(goal.current_amount + value, Decimal("0")))
    db.add(
        GoalContribution(
            goal_id=goal.id,
            user_id=user.id,
            contribution_date=contribution_date,
            amount=value,
            notes=notes,
            created_at=utc_now(),
        )
    )
    db.flush()
    return goal


def _effective_debt_balance(debt: Debt) -> Decimal:
    if debt.linked_account is not None:
        return _q(abs(debt.linked_account.current_balance))
    return _q(max(debt.balance, Decimal("0")))


@dataclass
class DebtSimulation:
    payoff_dates: dict[int, date | None]
    interest_paid: dict[int, Decimal]
    total_interest: Decimal
    total_months: int | None


def _strategy_order(debts: list[Debt], strategy: str, balances: dict[int, Decimal]) -> list[Debt]:
    if strategy == "avalanche":
        return sorted(debts, key=lambda debt: (-debt.apr, balances[debt.id], debt.id))
    if strategy == "snowball":
        return sorted(debts, key=lambda debt: (balances[debt.id], -debt.apr, debt.id))
    return sorted(debts, key=lambda debt: (debt.strategy_priority, debt.id))


def _simulate_debts(
    debts: list[Debt],
    strategy: str,
    global_extra: Decimal,
    today: date,
    *,
    include_individual_extra: bool,
) -> DebtSimulation:
    balances = {debt.id: _effective_debt_balance(debt) for debt in debts}
    interest_paid = {debt.id: Decimal("0") for debt in debts}
    payoff_dates: dict[int, date | None] = {debt.id: None for debt in debts}
    active = [debt for debt in debts if balances[debt.id] > 0]
    if not active:
        return DebtSimulation(payoff_dates, interest_paid, Decimal("0"), 0)

    base_pool = sum((debt.minimum_payment for debt in active), Decimal("0"))
    if include_individual_extra:
        base_pool += sum((debt.extra_payment for debt in active), Decimal("0"))
    base_pool += max(global_extra, Decimal("0"))
    if base_pool <= 0:
        return DebtSimulation(payoff_dates, interest_paid, Decimal("0"), None)

    for month_index in range(1, 601):
        active = [debt for debt in debts if balances[debt.id] > Decimal("0.00005")]
        if not active:
            return DebtSimulation(
                payoff_dates,
                interest_paid,
                _q(sum(interest_paid.values(), Decimal("0"))),
                month_index - 1,
            )
        for debt in active:
            interest = balances[debt.id] * debt.apr / Decimal("1200")
            interest_paid[debt.id] += interest
            balances[debt.id] += interest

        pool = base_pool
        for debt in active:
            required = min(debt.minimum_payment, balances[debt.id], pool)
            balances[debt.id] -= required
            pool -= required

        if include_individual_extra:
            for debt in active:
                extra = min(debt.extra_payment, balances[debt.id], pool)
                balances[debt.id] -= extra
                pool -= extra

        order = _strategy_order(active, strategy, balances)
        for debt in order:
            if pool <= 0:
                break
            payment = min(pool, balances[debt.id])
            balances[debt.id] -= payment
            pool -= payment

        for debt in active:
            if balances[debt.id] <= Decimal("0.00005") and payoff_dates[debt.id] is None:
                absolute = today.year * 12 + today.month - 1 + month_index
                year, month0 = divmod(absolute, 12)
                payoff_dates[debt.id] = date(year, month0 + 1, 1)

    return DebtSimulation(
        payoff_dates,
        interest_paid,
        _q(sum(interest_paid.values(), Decimal("0"))),
        None,
    )


def _strategy_settings(db: Session, user: User) -> DebtStrategySettings:
    settings = db.get(DebtStrategySettings, user.id)
    if settings is None:
        settings = DebtStrategySettings(
            user_id=user.id, strategy="avalanche", monthly_extra_budget=Decimal("0")
        )
        db.add(settings)
        db.flush()
    return settings


def list_debts(db: Session, user: User) -> dict[str, object]:
    debts = list(
        db.scalars(
            select(Debt)
            .options(joinedload(Debt.linked_account).joinedload(Account.institution))
            .where(Debt.user_id == user.id)
            .order_by(Debt.active.desc(), Debt.strategy_priority, Debt.id)
        ).all()
    )
    settings = _strategy_settings(db, user)
    active = [
        debt for debt in debts if debt.active and _effective_debt_balance(debt) > Decimal("0")
    ]
    today = _today(user)
    minimum_sim = _simulate_debts(
        active, settings.strategy, Decimal("0"), today, include_individual_extra=False
    )
    plan_sim = _simulate_debts(
        active,
        settings.strategy,
        settings.monthly_extra_budget,
        today,
        include_individual_extra=True,
    )
    rows: list[dict[str, object]] = []
    for debt in debts:
        balance = _effective_debt_balance(debt)
        saved = _q(
            max(
                minimum_sim.interest_paid.get(debt.id, Decimal("0"))
                - plan_sim.interest_paid.get(debt.id, Decimal("0")),
                Decimal("0"),
            )
        )
        rows.append(
            {
                "id": debt.id,
                "name": debt.name,
                "debt_type": debt.debt_type,
                "balance": money(balance),
                "apr": money(debt.apr),
                "minimum_payment": money(debt.minimum_payment),
                "extra_payment": money(debt.extra_payment),
                "strategy_priority": debt.strategy_priority,
                "due_day": debt.due_day,
                "active": debt.active,
                "notes": debt.notes,
                "linked_account": (
                    account_view(debt.linked_account) if debt.linked_account else None
                ),
                "minimum_payoff_date": minimum_sim.payoff_dates.get(debt.id),
                "planned_payoff_date": plan_sim.payoff_dates.get(debt.id),
                "interest_saved": money(saved),
            }
        )
    total_balance = sum((_effective_debt_balance(debt) for debt in active), Decimal("0"))
    minimums = sum((debt.minimum_payment for debt in active), Decimal("0"))
    extras = (
        sum((debt.extra_payment for debt in active), Decimal("0"))
        + settings.monthly_extra_budget
    )
    return {
        "currency": user.settings.currency,
        "strategy": settings.strategy,
        "monthly_extra_budget": money(settings.monthly_extra_budget),
        "total_balance": money(_q(total_balance)),
        "total_minimums": money(_q(minimums)),
        "planned_monthly_payment": money(_q(minimums + extras)),
        "minimum_total_interest": money(minimum_sim.total_interest),
        "planned_total_interest": money(plan_sim.total_interest),
        "interest_saved": money(
            _q(max(minimum_sim.total_interest - plan_sim.total_interest, Decimal("0")))
        ),
        "minimum_debt_free_date": max(
            (d for d in minimum_sim.payoff_dates.values() if d), default=None
        ),
        "planned_debt_free_date": max(
            (d for d in plan_sim.payoff_dates.values() if d), default=None
        ),
        "debts": rows,
    }


def _ensure_debt_account_available(
    db: Session, user: User, account: Account | None, *, exclude_debt_id: int | None = None
) -> None:
    if account is None:
        return
    statement = select(Debt.id).where(
        Debt.user_id == user.id, Debt.linked_account_id == account.id
    )
    if exclude_debt_id is not None:
        statement = statement.where(Debt.id != exclude_debt_id)
    if db.scalar(statement) is not None:
        raise ApiError(
            422,
            "debt_account_already_linked",
            "That account is already linked to another debt",
        )


def create_debt(db: Session, user: User, payload: dict[str, Any]) -> Debt:
    account = _owned_account(
        db, user, payload.get("linked_account_id"), allowed_types={"credit", "loan"}
    )
    _ensure_debt_account_available(db, user, account)
    debt = Debt(
        user_id=user.id,
        linked_account_id=account.id if account else None,
        name=str(payload["name"]).strip(),
        debt_type=str(payload["debt_type"]),
        balance=_q(Decimal(payload["balance"])),
        apr=_q(Decimal(payload["apr"])),
        minimum_payment=_q(Decimal(payload["minimum_payment"])),
        extra_payment=_q(Decimal(payload["extra_payment"])),
        strategy_priority=int(payload["strategy_priority"]),
        due_day=payload.get("due_day"),
        active=bool(payload["active"]),
        notes=payload.get("notes"),
    )
    db.add(debt)
    db.flush()
    return debt


def update_debt(db: Session, user: User, debt_id: int, payload: dict[str, Any]) -> Debt:
    debt = db.scalar(select(Debt).where(Debt.id == debt_id, Debt.user_id == user.id))
    if debt is None:
        raise ApiError(404, "debt_not_found", "Debt was not found")
    if "linked_account_id" in payload:
        account = _owned_account(
            db, user, payload["linked_account_id"], allowed_types={"credit", "loan"}
        )
        _ensure_debt_account_available(db, user, account, exclude_debt_id=debt.id)
        debt.linked_account_id = account.id if account else None
    for field in ("name", "debt_type", "strategy_priority", "active"):
        if field in payload:
            value = payload[field]
            if value is None:
                raise ApiError(422, "invalid_debt", f"{field} may not be null")
            setattr(debt, field, value.strip() if field == "name" else value)
    for field in ("due_day", "notes"):
        if field in payload:
            setattr(debt, field, payload[field])
    for field in ("balance", "apr", "minimum_payment", "extra_payment"):
        if field in payload:
            value = payload[field]
            if value is None:
                raise ApiError(422, "invalid_debt", f"{field} may not be null")
            setattr(debt, field, _q(Decimal(value)))
    db.flush()
    return debt


def delete_debt(db: Session, user: User, debt_id: int) -> None:
    debt = db.scalar(select(Debt).where(Debt.id == debt_id, Debt.user_id == user.id))
    if debt is None:
        raise ApiError(404, "debt_not_found", "Debt was not found")
    db.delete(debt)
    db.flush()


def update_debt_strategy(
    db: Session, user: User, strategy: str, extra: Decimal
) -> DebtStrategySettings:
    settings = _strategy_settings(db, user)
    settings.strategy = strategy
    settings.monthly_extra_budget = _q(extra)
    db.flush()
    return settings


def _forecast_settings(db: Session, user: User) -> ForecastAssumptions:
    settings = db.get(ForecastAssumptions, user.id)
    if settings is None:
        settings = ForecastAssumptions(
            user_id=user.id, reserve_balance=Decimal("0"), include_budget_reserve=True
        )
        db.add(settings)
        db.flush()
    return settings


def update_forecast_assumptions(
    db: Session, user: User, reserve_balance: Decimal, include_budget_reserve: bool
) -> ForecastAssumptions:
    settings = _forecast_settings(db, user)
    settings.reserve_balance = _q(reserve_balance)
    settings.include_budget_reserve = include_budget_reserve
    db.flush()
    return settings


def _cash_available(db: Session, user: User) -> Decimal:
    accounts = list(
        db.scalars(
            select(Account).where(
                Account.user_id == user.id,
                Account.currency == user.settings.currency,
                Account.account_type == "depository",
            )
        ).all()
    )
    return _q(
        sum(
            (
                account.available_balance
                if account.available_balance is not None
                else account.current_balance
                for account in accounts
            ),
            Decimal("0"),
        )
    )


def _recurring_occurrences(stream: RecurringStream, today: date, end: date) -> list[date]:
    step = CADENCE_DAYS[stream.cadence]
    current = stream.next_expected_date
    while current < today:
        current += timedelta(days=step)
    result: list[date] = []
    while current <= end:
        result.append(current)
        current += timedelta(days=step)
    return result


def _monthly_plan_reserves(
    db: Session, user: User, start: date, end: date
) -> tuple[Decimal, Decimal, Decimal]:
    general_total = Decimal("0")
    savings_total = Decimal("0")
    debt_total = Decimal("0")
    current = date(start.year, start.month, 1)
    while current <= end:
        view = month_budget_view(db, user, current.strftime("%Y-%m"))
        days_in_month = calendar.monthrange(current.year, current.month)[1]
        overlap_start = max(start, current)
        overlap_end = min(end, date(current.year, current.month, days_in_month))
        days = max((overlap_end - overlap_start).days + 1, 0)
        if days:
            factor = Decimal(days) / Decimal(days_in_month)
            rows = cast(list[dict[str, object]], view["categories"])
            for row in rows:
                category = cast(dict[str, object], row["category"])
                key = cast(str, category["key"])
                amount = Decimal(cast(str, row["base_amount"])) * factor
                if key == "savings":
                    savings_total += amount
                elif key == "debt_payments":
                    debt_total += amount
                else:
                    general_total += amount
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return _q(general_total), _q(savings_total), _q(debt_total)


def _planned_income_fallback(db: Session, user: User, start: date, end: date) -> Decimal:
    total = Decimal("0")
    current = date(start.year, start.month, 1)
    while current <= end:
        view = month_budget_view(db, user, current.strftime("%Y-%m"))
        days_in_month = calendar.monthrange(current.year, current.month)[1]
        overlap_start = max(start, current)
        overlap_end = min(end, date(current.year, current.month, days_in_month))
        days = max((overlap_end - overlap_start).days + 1, 0)
        if days:
            total += (
                Decimal(cast(str, view["planned_income"]))
                * Decimal(days)
                / Decimal(days_in_month)
            )
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return _q(total)


def forecast_view(
    db: Session,
    user: User,
    *,
    extra_debt_payment: Decimal = Decimal("0"),
    goal_contribution_adjustment: Decimal = Decimal("0"),
    spending_reduction: Decimal = Decimal("0"),
    new_monthly_expense: Decimal = Decimal("0"),
) -> dict[str, object]:
    today = _today(user)
    cash = _cash_available(db, user)
    assumptions = _forecast_settings(db, user)
    active_goals = list(
        db.scalars(
            select(FinancialGoal)
            .options(joinedload(FinancialGoal.linked_account))
            .where(FinancialGoal.user_id == user.id, FinancialGoal.active.is_(True))
        ).all()
    )
    goal_reserves = _linked_goal_reserve(active_goals)
    spendable_cash = _q(cash - goal_reserves)
    goals = [goal for goal in active_goals if _goal_current(goal) < goal.target_amount]
    debts = list(
        db.scalars(
            select(Debt)
            .options(joinedload(Debt.linked_account))
            .where(Debt.user_id == user.id, Debt.active.is_(True))
        ).all()
    )
    debts = [debt for debt in debts if _effective_debt_balance(debt) > 0]
    strategy = _strategy_settings(db, user)
    recurring = list(
        db.scalars(
            select(RecurringStream).where(
                RecurringStream.user_id == user.id, RecurringStream.active.is_(True)
            )
        ).all()
    )
    has_recurring_income = any(stream.kind == "income" for stream in recurring)
    monthly_goal = max(
        sum((goal.monthly_contribution for goal in goals), Decimal("0"))
        + goal_contribution_adjustment,
        Decimal("0"),
    )
    monthly_debt = Decimal("0")
    if debts:
        monthly_debt = (
            sum((debt.minimum_payment + debt.extra_payment for debt in debts), Decimal("0"))
            + strategy.monthly_extra_budget
            + extra_debt_payment
        )

    horizon_rows: list[dict[str, object]] = []
    for days in (30, 60, 90):
        end = today + timedelta(days=days)
        recurring_income = Decimal("0")
        recurring_expense = Decimal("0")
        for stream in recurring:
            count = len(_recurring_occurrences(stream, today, end))
            amount = stream.average_amount * Decimal(count)
            if stream.kind == "income":
                recurring_income += amount
            else:
                recurring_expense += amount
        income = (
            recurring_income
            if has_recurring_income
            else _planned_income_fallback(db, user, today, end)
        )
        month_factor = Decimal(days) / Decimal("30")
        debt_payments = max(monthly_debt, Decimal("0")) * month_factor
        goal_contributions = monthly_goal * month_factor
        flexible = Decimal("0")
        if assumptions.include_budget_reserve:
            general_budget, savings_budget, debt_budget = _monthly_plan_reserves(
                db, user, today, end
            )
            general_reserve = max(general_budget - recurring_expense, Decimal("0"))
            general_reserve = max(
                general_reserve - max(spending_reduction, Decimal("0")) * month_factor,
                Decimal("0"),
            )
            savings_reserve = max(savings_budget - goal_contributions, Decimal("0"))
            debt_reserve = max(debt_budget - debt_payments, Decimal("0"))
            flexible = general_reserve + savings_reserve + debt_reserve
        added_expense = max(new_monthly_expense, Decimal("0")) * month_factor
        projected = (
            spendable_cash
            + income
            - recurring_expense
            - flexible
            - debt_payments
            - goal_contributions
            - added_expense
        )
        horizon_rows.append(
            {
                "days": days,
                "date": end,
                "starting_cash": money(spendable_cash),
                "income": money(_q(income)),
                "recurring_expenses": money(_q(recurring_expense)),
                "budget_reserve": money(_q(flexible)),
                "debt_payments": money(_q(debt_payments)),
                "goal_contributions": money(_q(goal_contributions)),
                "new_expenses": money(_q(added_expense)),
                "projected_balance": money(_q(projected)),
                "above_reserve": money(_q(projected - assumptions.reserve_balance)),
            }
        )

    upcoming: list[dict[str, object]] = []
    for stream in recurring:
        for occurrence in _recurring_occurrences(stream, today, today + timedelta(days=45)):
            upcoming.append(
                {
                    "date": occurrence,
                    "name": stream.display_name,
                    "kind": stream.kind,
                    "amount": money(stream.average_amount),
                }
            )
    upcoming.sort(
        key=lambda item: (cast(date, item["date"]), cast(str, item["name"]))
    )
    return {
        "currency": user.settings.currency,
        "as_of": today,
        "cash_available": money(cash),
        "goal_reserves": money(goal_reserves),
        "spendable_cash": money(spendable_cash),
        "reserve_balance": money(assumptions.reserve_balance),
        "include_budget_reserve": assumptions.include_budget_reserve,
        "horizons": horizon_rows,
        "upcoming": upcoming[:20],
    }


def scenario_view(db: Session, user: User, payload: dict[str, Decimal]) -> dict[str, object]:
    baseline = forecast_view(db, user)
    scenario = forecast_view(
        db,
        user,
        extra_debt_payment=payload["extra_debt_payment"],
        goal_contribution_adjustment=payload["goal_contribution_adjustment"],
        spending_reduction=payload["spending_reduction"],
        new_monthly_expense=payload["new_monthly_expense"],
    )
    baseline_horizons = cast(list[dict[str, object]], baseline["horizons"])
    scenario_horizons = cast(list[dict[str, object]], scenario["horizons"])
    baseline_90 = Decimal(cast(str, baseline_horizons[-1]["projected_balance"]))
    scenario_90 = Decimal(cast(str, scenario_horizons[-1]["projected_balance"]))

    settings = _strategy_settings(db, user)
    debts = list(
        db.scalars(
            select(Debt)
            .options(joinedload(Debt.linked_account))
            .where(Debt.user_id == user.id, Debt.active.is_(True))
        ).all()
    )
    today = _today(user)
    base_debt = _simulate_debts(
        debts,
        settings.strategy,
        settings.monthly_extra_budget,
        today,
        include_individual_extra=True,
    )
    scenario_debt = _simulate_debts(
        debts,
        settings.strategy,
        settings.monthly_extra_budget + payload["extra_debt_payment"],
        today,
        include_individual_extra=True,
    )
    return {
        "baseline": baseline,
        "scenario": scenario,
        "cash_impact_90_days": money(_q(scenario_90 - baseline_90)),
        "baseline_debt_free_date": max(
            (d for d in base_debt.payoff_dates.values() if d), default=None
        ),
        "scenario_debt_free_date": max(
            (d for d in scenario_debt.payoff_dates.values() if d), default=None
        ),
        "interest_saved": money(
            _q(max(base_debt.total_interest - scenario_debt.total_interest, Decimal("0")))
        ),
    }
