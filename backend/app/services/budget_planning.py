from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ApiError
from app.models import (
    Account,
    AnnualBudgetCategory,
    AnnualBudgetMonthAllocation,
    AnnualBudgetPlan,
    Category,
    Debt,
    DebtStrategySettings,
    FinancialGoal,
    MonthlyBudget,
    MonthlyBudgetCategory,
    RecurringStream,
    Transaction,
    User,
)
from app.services.catalog import CATEGORY_BY_KEY
from app.services.transaction_intelligence import effective_category, effective_kind
from app.services.views import money

MONEY = Decimal("0.0001")
ROLLOVER_MODES = {"off", "surplus", "surplus_and_deficit"}
DISTRIBUTIONS = {"even", "monthly", "custom"}


def _q(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _parse_month(value: str) -> date:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ApiError(422, "invalid_month", "Month must use YYYY-MM format") from exc
    if parsed.strftime("%Y-%m") != value:
        raise ApiError(422, "invalid_month", "Month must use YYYY-MM format")
    return date(parsed.year, parsed.month, 1)


def _parse_year(value: int) -> int:
    if value < 2000 or value > 2200:
        raise ApiError(422, "invalid_year", "Year must be between 2000 and 2200")
    return value


def _month_end(month_start: date) -> date:
    return date(
        month_start.year,
        month_start.month,
        calendar.monthrange(month_start.year, month_start.month)[1],
    )


def _category_metadata(category: Category) -> dict[str, object]:
    definition = CATEGORY_BY_KEY.get(category.stable_key)
    return {
        "id": category.id,
        "key": category.stable_key,
        "name": category.name,
        "group": definition["group"] if definition else "Custom",
        "enabled": category.enabled,
    }


def _owned_categories(db: Session, user: User, category_ids: set[int]) -> dict[int, Category]:
    if not category_ids:
        return {}
    categories = list(
        db.scalars(
            select(Category).where(Category.user_id == user.id, Category.id.in_(category_ids))
        ).all()
    )
    found = {category.id: category for category in categories}
    if found.keys() != category_ids:
        raise ApiError(404, "category_not_found", "One or more categories were not found")
    return found


def _annual_plan(db: Session, user: User, year: int) -> AnnualBudgetPlan | None:
    return db.scalar(
        select(AnnualBudgetPlan).where(
            AnnualBudgetPlan.user_id == user.id, AnnualBudgetPlan.year == year
        )
    )


def _annual_categories(
    db: Session, user: User, plan_id: int
) -> list[AnnualBudgetCategory]:
    return list(
        db.scalars(
            select(AnnualBudgetCategory)
            .options(joinedload(AnnualBudgetCategory.category))
            .where(
                AnnualBudgetCategory.user_id == user.id,
                AnnualBudgetCategory.plan_id == plan_id,
            )
            .order_by(AnnualBudgetCategory.category_id)
        ).all()
    )


def _annual_custom_months(
    db: Session, annual_category_ids: list[int]
) -> dict[int, dict[int, Decimal]]:
    if not annual_category_ids:
        return {}
    rows = db.execute(
        select(
            AnnualBudgetMonthAllocation.annual_category_id,
            AnnualBudgetMonthAllocation.month_number,
            AnnualBudgetMonthAllocation.amount,
        ).where(AnnualBudgetMonthAllocation.annual_category_id.in_(annual_category_ids))
    ).all()
    result: dict[int, dict[int, Decimal]] = defaultdict(dict)
    for category_id, month_number, amount in rows:
        result[int(category_id)][int(month_number)] = Decimal(amount)
    return dict(result)


def put_annual_plan(
    db: Session, user: User, year: int, payload: dict[str, Any]
) -> AnnualBudgetPlan:
    year = _parse_year(year)
    entries = payload.get("categories", [])
    category_ids = [int(item["category_id"]) for item in entries]
    if len(category_ids) != len(set(category_ids)):
        raise ApiError(422, "duplicate_budget_category", "Each category may appear only once")
    _owned_categories(db, user, set(category_ids))

    plan = _annual_plan(db, user, year)
    if plan is None:
        plan = AnnualBudgetPlan(user_id=user.id, year=year)
        db.add(plan)
        db.flush()
    plan.planned_income = _q(Decimal(payload["planned_income"]))
    plan.notes = payload.get("notes")

    existing = _annual_categories(db, user, plan.id)
    existing_by_category = {row.category_id: row for row in existing}
    keep_ids: set[int] = set()
    for item in entries:
        category_id = int(item["category_id"])
        distribution = str(item["distribution"])
        rollover_mode = str(item["rollover_mode"])
        if distribution not in DISTRIBUTIONS or rollover_mode not in ROLLOVER_MODES:
            raise ApiError(422, "invalid_budget_configuration", "Budget configuration is invalid")

        monthly_amount: Decimal | None = None
        custom_months = item.get("custom_months") or []
        annual_amount: Decimal
        if distribution == "monthly":
            monthly_value = item.get("monthly_amount")
            if monthly_value is None:
                raise ApiError(422, "monthly_amount_required", "Monthly amount is required")
            monthly_amount = _q(Decimal(monthly_value))
            annual_amount = _q(monthly_amount * Decimal("12"))
        elif distribution == "custom":
            if len(custom_months) != 12:
                raise ApiError(
                    422,
                    "custom_months_required",
                    "Custom distribution requires all 12 monthly amounts",
                )
            month_numbers = {int(value["month"]) for value in custom_months}
            if month_numbers != set(range(1, 13)):
                raise ApiError(
                    422,
                    "custom_months_required",
                    "Custom distribution requires months 1 through 12",
                )
            annual_amount = _q(
                sum((Decimal(value["amount"]) for value in custom_months), Decimal("0"))
            )
        else:
            annual_amount = _q(Decimal(item["annual_amount"]))

        row = existing_by_category.get(category_id)
        if row is None:
            row = AnnualBudgetCategory(
                plan_id=plan.id,
                user_id=user.id,
                category_id=category_id,
            )
            db.add(row)
            db.flush()
        row.annual_amount = annual_amount
        row.distribution = distribution
        row.monthly_amount = monthly_amount
        row.rollover_mode = rollover_mode
        keep_ids.add(row.id)

        db.execute(
            delete(AnnualBudgetMonthAllocation).where(
                AnnualBudgetMonthAllocation.annual_category_id == row.id
            )
        )
        if distribution == "custom":
            for value in custom_months:
                db.add(
                    AnnualBudgetMonthAllocation(
                        annual_category_id=row.id,
                        month_number=int(value["month"]),
                        amount=_q(Decimal(value["amount"])),
                    )
                )

    for row in existing:
        if row.id not in keep_ids:
            db.delete(row)
    db.flush()
    return plan


def annual_plan_view(db: Session, user: User, year: int) -> dict[str, object]:
    year = _parse_year(year)
    plan = _annual_plan(db, user, year)
    if plan is None:
        return {
            "year": year,
            "exists": False,
            "planned_income": "0.0000",
            "notes": None,
            "categories": [],
        }
    categories = _annual_categories(db, user, plan.id)
    custom = _annual_custom_months(db, [row.id for row in categories])
    return {
        "year": year,
        "exists": True,
        "planned_income": money(plan.planned_income),
        "notes": plan.notes,
        "categories": [
            {
                "category": _category_metadata(row.category),
                "annual_amount": money(row.annual_amount),
                "distribution": row.distribution,
                "monthly_amount": money(row.monthly_amount),
                "rollover_mode": row.rollover_mode,
                "custom_months": [
                    {"month": month_number, "amount": money(custom.get(row.id, {}).get(month_number, Decimal("0")))}
                    for month_number in range(1, 13)
                ]
                if row.distribution == "custom"
                else [],
            }
            for row in categories
        ],
    }


def _annual_month_base(
    db: Session, user: User, month_start: date
) -> tuple[Decimal, dict[int, tuple[Decimal, str]], bool]:
    plan = _annual_plan(db, user, month_start.year)
    if plan is None:
        return Decimal("0"), {}, False
    rows = _annual_categories(db, user, plan.id)
    custom = _annual_custom_months(db, [row.id for row in rows])
    result: dict[int, tuple[Decimal, str]] = {}
    for row in rows:
        if row.distribution == "custom":
            amount = custom.get(row.id, {}).get(month_start.month, Decimal("0"))
        elif row.distribution == "monthly" and row.monthly_amount is not None:
            amount = row.monthly_amount
        else:
            amount = _q(row.annual_amount / Decimal("12"))
        result[row.category_id] = (_q(amount), row.rollover_mode)
    return _q(plan.planned_income / Decimal("12")), result, True


def _monthly_budget(db: Session, user: User, month_start: date) -> MonthlyBudget | None:
    return db.scalar(
        select(MonthlyBudget).where(
            MonthlyBudget.user_id == user.id, MonthlyBudget.month == month_start
        )
    )


def _monthly_categories(
    db: Session, user: User, budget_id: int
) -> list[MonthlyBudgetCategory]:
    return list(
        db.scalars(
            select(MonthlyBudgetCategory)
            .options(joinedload(MonthlyBudgetCategory.category))
            .where(
                MonthlyBudgetCategory.user_id == user.id,
                MonthlyBudgetCategory.budget_id == budget_id,
            )
            .order_by(MonthlyBudgetCategory.category_id)
        ).all()
    )


def _month_base(
    db: Session, user: User, month_start: date
) -> tuple[Decimal, dict[int, tuple[Decimal, str]], str]:
    annual_income, annual_categories, annual_exists = _annual_month_base(db, user, month_start)
    monthly = _monthly_budget(db, user, month_start)
    if monthly is None:
        return (
            annual_income,
            annual_categories,
            "annual" if annual_exists else "unplanned",
        )
    monthly_rows = _monthly_categories(db, user, monthly.id)
    row_map = {
        row.category_id: (_q(row.planned_amount), row.rollover_mode) for row in monthly_rows
    }
    income = _q(monthly.planned_income) if monthly.planned_income is not None else annual_income
    if monthly.mode == "standalone":
        return income, row_map, "standalone"
    merged = dict(annual_categories)
    merged.update(row_map)
    return income, merged, "override"


def put_monthly_budget(
    db: Session, user: User, month: str, payload: dict[str, Any]
) -> MonthlyBudget:
    month_start = _parse_month(month)
    mode = str(payload["mode"])
    if mode == "override" and _annual_plan(db, user, month_start.year) is None:
        raise ApiError(
            422,
            "annual_plan_required",
            "Monthly override mode requires an annual budget plan for this year",
        )
    entries = payload.get("categories", [])
    category_ids = [int(item["category_id"]) for item in entries]
    if len(category_ids) != len(set(category_ids)):
        raise ApiError(422, "duplicate_budget_category", "Each category may appear only once")
    _owned_categories(db, user, set(category_ids))

    budget = _monthly_budget(db, user, month_start)
    if budget is None:
        budget = MonthlyBudget(user_id=user.id, month=month_start)
        db.add(budget)
        db.flush()
    budget.mode = mode
    planned_income = payload.get("planned_income")
    budget.planned_income = _q(Decimal(planned_income)) if planned_income is not None else None
    budget.notes = payload.get("notes")

    db.execute(
        delete(MonthlyBudgetCategory).where(MonthlyBudgetCategory.budget_id == budget.id)
    )
    for item in entries:
        rollover_mode = str(item["rollover_mode"])
        if rollover_mode not in ROLLOVER_MODES:
            raise ApiError(422, "invalid_rollover_mode", "Rollover mode is invalid")
        db.add(
            MonthlyBudgetCategory(
                budget_id=budget.id,
                user_id=user.id,
                category_id=int(item["category_id"]),
                planned_amount=_q(Decimal(item["planned_amount"])),
                rollover_mode=rollover_mode,
            )
        )
    db.flush()
    return budget


def delete_monthly_budget(db: Session, user: User, month: str) -> None:
    month_start = _parse_month(month)
    budget = _monthly_budget(db, user, month_start)
    if budget is None:
        return
    db.delete(budget)
    db.flush()


def copy_previous_month(db: Session, user: User, month: str) -> MonthlyBudget:
    target = _parse_month(month)
    if target.month == 1:
        previous = date(target.year - 1, 12, 1)
    else:
        previous = date(target.year, target.month - 1, 1)
    previous_income, previous_categories, previous_source = _month_base(db, user, previous)
    if previous_source == "unplanned" and not previous_categories:
        raise ApiError(404, "previous_budget_not_found", "The previous month has no budget to copy")
    budget = _monthly_budget(db, user, target)
    if budget is None:
        budget = MonthlyBudget(user_id=user.id, month=target)
        db.add(budget)
        db.flush()
    budget.mode = "standalone"
    budget.planned_income = previous_income
    budget.notes = f"Copied from {previous.strftime('%Y-%m')}"
    db.execute(
        delete(MonthlyBudgetCategory).where(MonthlyBudgetCategory.budget_id == budget.id)
    )
    for category_id, (amount, rollover_mode) in previous_categories.items():
        db.add(
            MonthlyBudgetCategory(
                budget_id=budget.id,
                user_id=user.id,
                category_id=category_id,
                planned_amount=amount,
                rollover_mode=rollover_mode,
            )
        )
    db.flush()
    return budget


def _month_actuals(
    db: Session, user: User, month_start: date
) -> tuple[Decimal, dict[int, Decimal], Decimal]:
    end = _month_end(month_start)
    transactions = list(
        db.scalars(
            select(Transaction)
            .options(
                joinedload(Transaction.category),
                joinedload(Transaction.user_category_override),
            )
            .where(
                Transaction.user_id == user.id,
                Transaction.posted_date >= month_start,
                Transaction.posted_date <= end,
            )
        ).all()
    )
    income = Decimal("0")
    spending_by_category: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    total_spending = Decimal("0")
    for transaction in transactions:
        if transaction.excluded_from_spending:
            continue
        kind = effective_kind(transaction)
        category = effective_category(transaction)
        if kind == "income":
            income += transaction.amount
        elif kind == "expense":
            amount = -transaction.amount
            total_spending += amount
            if category is not None:
                spending_by_category[category.id] += amount
        elif kind == "refund":
            total_spending -= transaction.amount
            if category is not None:
                spending_by_category[category.id] -= transaction.amount
    return _q(income), {key: _q(value) for key, value in spending_by_category.items()}, _q(total_spending)


def _rollover_for_month(
    db: Session, user: User, target: date
) -> dict[int, Decimal]:
    carries: dict[int, Decimal] = {}
    for month_number in range(1, target.month + 1):
        month_start = date(target.year, month_number, 1)
        _, config, _ = _month_base(db, user, month_start)
        _, actuals, _ = _month_actuals(db, user, month_start)
        current_carries = {category_id: carries.get(category_id, Decimal("0")) for category_id in config}
        if month_number == target.month:
            return {key: _q(value) for key, value in current_carries.items()}
        next_carries: dict[int, Decimal] = {}
        for category_id, (base_amount, mode) in config.items():
            available = base_amount + current_carries.get(category_id, Decimal("0"))
            delta = available - actuals.get(category_id, Decimal("0"))
            if mode == "surplus":
                next_carries[category_id] = max(_q(delta), Decimal("0"))
            elif mode == "surplus_and_deficit":
                next_carries[category_id] = _q(delta)
        carries = next_carries
    return {}


def _cash_available(db: Session, user: User) -> Decimal:
    accounts = db.scalars(
        select(Account).where(Account.user_id == user.id, Account.currency == user.settings.currency)
    ).all()
    return _q(
        sum(
            (
                account.available_balance
                if account.available_balance is not None
                else account.current_balance
                for account in accounts
                if account.account_type == "depository"
            ),
            Decimal("0"),
        )
    )


def _upcoming_recurring(db: Session, user: User, month_start: date) -> Decimal:
    today = datetime.now(ZoneInfo(user.settings.timezone)).date()
    end = _month_end(month_start)
    lower = max(month_start, today)
    if lower > end:
        return Decimal("0")
    streams = db.scalars(
        select(RecurringStream).where(
            RecurringStream.user_id == user.id,
            RecurringStream.active.is_(True),
            RecurringStream.kind == "expense",
            RecurringStream.next_expected_date >= lower,
            RecurringStream.next_expected_date <= end,
        )
    ).all()
    return _q(sum((stream.average_amount for stream in streams), Decimal("0")))


def month_budget_view(db: Session, user: User, month: str) -> dict[str, object]:
    month_start = _parse_month(month)
    planned_income, config, source = _month_base(db, user, month_start)
    carries = _rollover_for_month(db, user, month_start)
    actual_income, actuals, actual_spending = _month_actuals(db, user, month_start)
    category_ids = set(config) | set(actuals)
    categories = _owned_categories(db, user, category_ids)

    rows: list[dict[str, object]] = []
    total_budgeted = Decimal("0")
    total_available = Decimal("0")
    for category_id in sorted(category_ids, key=lambda cid: categories[cid].name.casefold()):
        base_amount, rollover_mode = config.get(category_id, (Decimal("0"), "off"))
        rollover_amount = carries.get(category_id, Decimal("0")) if category_id in config else Decimal("0")
        available = _q(base_amount + rollover_amount)
        spent = actuals.get(category_id, Decimal("0"))
        remaining = _q(available - spent)
        total_budgeted += base_amount
        total_available += available
        if available <= 0:
            status = "no_budget" if spent > 0 else "on_track"
            percent = None
        else:
            ratio = spent / available * Decimal("100")
            percent = _q(ratio)
            if spent > available:
                status = "over"
            elif ratio >= Decimal("80"):
                status = "close"
            else:
                status = "on_track"
        rows.append(
            {
                "category": _category_metadata(categories[category_id]),
                "base_amount": money(base_amount),
                "rollover_amount": money(rollover_amount),
                "available_amount": money(available),
                "spent_amount": money(spent),
                "remaining_amount": money(remaining),
                "percent_used": money(percent),
                "status": status,
                "rollover_mode": rollover_mode,
            }
        )

    unallocated = _q(planned_income - total_budgeted)
    remaining_planned = _q(
        sum(
            (
                max(
                    base_amount
                    + carries.get(category_id, Decimal("0"))
                    - actuals.get(category_id, Decimal("0")),
                    Decimal("0"),
                )
                for category_id, (base_amount, _) in config.items()
            ),
            Decimal("0"),
        )
    )
    upcoming_recurring = _upcoming_recurring(db, user, month_start)
    cash_available = _cash_available(db, user)

    savings_remaining = Decimal("0")
    debt_budget_remaining = Decimal("0")
    for category_id, category in categories.items():
        base_amount, _ = config.get(category_id, (Decimal("0"), "off"))
        available = base_amount + carries.get(category_id, Decimal("0"))
        remaining = max(available - actuals.get(category_id, Decimal("0")), Decimal("0"))
        if category.stable_key == "savings":
            savings_remaining += remaining
        elif category.stable_key == "debt_payments":
            debt_budget_remaining += remaining

    goals = list(
        db.scalars(
            select(FinancialGoal)
            .options(joinedload(FinancialGoal.linked_account))
            .where(FinancialGoal.user_id == user.id, FinancialGoal.active.is_(True))
        ).all()
    )
    goal_reserves = _q(
        sum(
            (
                min(max(goal.linked_account.current_balance, Decimal("0")), goal.target_amount)
                for goal in goals
                if goal.linked_account is not None
            ),
            Decimal("0"),
        )
    )
    goal_commitment = sum(
        (
            goal.monthly_contribution
            for goal in goals
            if (
                max(goal.linked_account.current_balance, Decimal("0"))
                if goal.linked_account is not None
                else goal.current_amount
            )
            < goal.target_amount
        ),
        Decimal("0"),
    )
    debts = list(
        db.scalars(
            select(Debt)
            .options(joinedload(Debt.linked_account))
            .where(Debt.user_id == user.id, Debt.active.is_(True))
        ).all()
    )
    debt_commitment = sum(
        (
            debt.minimum_payment + debt.extra_payment
            for debt in debts
            if (
                abs(debt.linked_account.current_balance)
                if debt.linked_account is not None
                else debt.balance
            )
            > 0
        ),
        Decimal("0"),
    )
    debt_strategy = db.get(DebtStrategySettings, user.id)
    if debt_strategy is not None:
        debt_commitment += debt_strategy.monthly_extra_budget
    planning_commitments = _q(
        max(goal_commitment - savings_remaining, Decimal("0"))
        + max(debt_commitment - debt_budget_remaining, Decimal("0"))
    )
    reserve = (
        max(remaining_planned, upcoming_recurring) + planning_commitments + goal_reserves
    )
    safe_to_spend = _q(cash_available - reserve)
    monthly = _monthly_budget(db, user, month_start)
    return {
        "period": {
            "month": month_start.strftime("%Y-%m"),
            "start": month_start,
            "end": _month_end(month_start),
        },
        "currency": user.settings.currency,
        "source": source,
        "monthly_mode": monthly.mode if monthly else None,
        "has_annual_plan": _annual_plan(db, user, month_start.year) is not None,
        "planned_income": money(planned_income),
        "actual_income": money(actual_income),
        "budgeted": money(total_budgeted),
        "available_with_rollover": money(total_available),
        "spent": money(actual_spending),
        "remaining": money(total_available - actual_spending),
        "unallocated": money(unallocated),
        "cash_available": money(cash_available),
        "upcoming_recurring": money(upcoming_recurring),
        "planning_commitments": money(planning_commitments),
        "goal_reserves": money(goal_reserves),
        "safe_to_spend": money(safe_to_spend),
        "notes": monthly.notes if monthly else None,
        "categories": rows,
    }


def year_budget_view(db: Session, user: User, year: int) -> dict[str, object]:
    year = _parse_year(year)
    today = datetime.now(ZoneInfo(user.settings.timezone)).date()
    ytd_end = date(year, 12, 31) if year < today.year else (today if year == today.year else date(year, 1, 1))
    through_month = 12 if year < today.year else (today.month if year == today.year else 0)

    category_planned: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    planned_income = Decimal("0")
    ytd_planned: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    ytd_income_plan = Decimal("0")
    for month_number in range(1, 13):
        month_start = date(year, month_number, 1)
        month_income, config, _ = _month_base(db, user, month_start)
        planned_income += month_income
        if month_number <= through_month:
            ytd_income_plan += month_income
        for category_id, (amount, _) in config.items():
            category_planned[category_id] += amount
            if month_number <= through_month:
                ytd_planned[category_id] += amount

    actual_income = Decimal("0")
    actuals: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    if through_month:
        transactions = list(
            db.scalars(
                select(Transaction)
                .options(
                    joinedload(Transaction.category),
                    joinedload(Transaction.user_category_override),
                )
                .where(
                    Transaction.user_id == user.id,
                    Transaction.posted_date >= date(year, 1, 1),
                    Transaction.posted_date <= ytd_end,
                )
            ).all()
        )
        for transaction in transactions:
            if transaction.excluded_from_spending:
                continue
            kind = effective_kind(transaction)
            category = effective_category(transaction)
            if kind == "income":
                actual_income += transaction.amount
            elif kind == "expense" and category is not None:
                actuals[category.id] += -transaction.amount
            elif kind == "refund" and category is not None:
                actuals[category.id] -= transaction.amount

    category_ids = set(category_planned) | set(actuals)
    categories = _owned_categories(db, user, category_ids)
    rows: list[dict[str, object]] = []
    for category_id in sorted(category_ids, key=lambda cid: categories[cid].name.casefold()):
        goal = _q(category_planned.get(category_id, Decimal("0")))
        ytd_goal = _q(ytd_planned.get(category_id, Decimal("0")))
        spent = _q(actuals.get(category_id, Decimal("0")))
        percent = _q(spent / goal * Decimal("100")) if goal > 0 else None
        rows.append(
            {
                "category": _category_metadata(categories[category_id]),
                "planned_amount": money(goal),
                "ytd_planned_amount": money(ytd_goal),
                "spent_amount": money(spent),
                "remaining_amount": money(goal - spent),
                "percent_used": money(percent),
            }
        )

    total_planned = _q(sum(category_planned.values(), Decimal("0")))
    total_spent = _q(sum(actuals.values(), Decimal("0")))
    return {
        "year": year,
        "currency": user.settings.currency,
        "has_annual_plan": _annual_plan(db, user, year) is not None,
        "planned_income": money(_q(planned_income)),
        "ytd_planned_income": money(_q(ytd_income_plan)),
        "actual_income": money(_q(actual_income)),
        "budgeted": money(total_planned),
        "spent": money(total_spent),
        "remaining": money(total_planned - total_spent),
        "unallocated": money(_q(planned_income - total_planned)),
        "categories": rows,
    }


def dashboard_budget_summary(db: Session, user: User, month: str) -> dict[str, object] | None:
    view = month_budget_view(db, user, month)
    if view["source"] == "unplanned" and not view["categories"]:
        return None
    categories = list(view["categories"])
    close_count = sum(1 for row in categories if row["status"] == "close")
    over_count = sum(1 for row in categories if row["status"] == "over")
    return {
        "budgeted": view["available_with_rollover"],
        "spent": view["spent"],
        "remaining": view["remaining"],
        "safe_to_spend": view["safe_to_spend"],
        "close_count": close_count,
        "over_count": over_count,
    }
