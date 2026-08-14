from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.security import utc_now
from app.models import Account, FinancialSnapshot, RecurringStream, Transaction, User
from app.services.budget_planning import month_budget_view, year_budget_view
from app.services.finance import dashboard_data
from app.services.financial_planning import forecast_view, list_debts, list_goals
from app.services.transaction_intelligence import (
    effective_category,
    effective_kind,
    effective_merchant,
    normalize_merchant,
)
from app.services.views import money

ReportRange = Literal["30d", "3m", "6m", "ytd", "1y"]


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _local_today(user: User) -> date:
    return datetime.now(ZoneInfo(user.settings.timezone)).date()


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _shift_months(value: date, months: int) -> date:
    index = value.year * 12 + (value.month - 1) + months
    year, zero_month = divmod(index, 12)
    month = zero_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _range_bounds(user: User, range_key: ReportRange) -> dict[str, object]:
    today = _local_today(user)
    if range_key == "30d":
        start = today - timedelta(days=29)
        previous_end = start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=29)
        label = "Last 30 days"
        bucket = "day"
    elif range_key in {"3m", "6m", "1y"}:
        months = {"3m": 3, "6m": 6, "1y": 12}[range_key]
        start = _shift_months(_month_start(today), -(months - 1))
        previous_end = start - timedelta(days=1)
        previous_start = _shift_months(_month_start(start), -months)
        label = {"3m": "Last 3 months", "6m": "Last 6 months", "1y": "Last 12 months"}[range_key]
        bucket = "month"
    else:
        start = date(today.year, 1, 1)
        previous_start = date(today.year - 1, 1, 1)
        previous_end = date(today.year - 1, today.month, min(today.day, calendar.monthrange(today.year - 1, today.month)[1]))
        label = "Year to date"
        bucket = "month"
    return {
        "key": range_key,
        "label": label,
        "start": start,
        "end": today,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "bucket": bucket,
    }


def _pct_change(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * Decimal("100")


def _included_account_ids(db: Session, user: User) -> list[int]:
    return list(
        db.scalars(
            select(Account.id).where(
                Account.user_id == user.id,
                Account.currency == user.settings.currency,
            )
        ).all()
    )


def _report_transactions(
    db: Session, user: User, start: date, end: date
) -> list[Transaction]:
    account_ids = _included_account_ids(db, user)
    if not account_ids:
        return []
    return list(
        db.scalars(
            select(Transaction)
            .options(
                joinedload(Transaction.category),
                joinedload(Transaction.user_category_override),
            )
            .where(
                Transaction.user_id == user.id,
                Transaction.account_id.in_(account_ids),
                Transaction.posted_date >= start,
                Transaction.posted_date <= end,
            )
            .order_by(Transaction.posted_date, Transaction.id)
        ).all()
    )


def _bucket_key(value: date, bucket: str) -> str:
    return value.isoformat() if bucket == "day" else value.strftime("%Y-%m")


def _series_keys(start: date, end: date, bucket: str) -> list[str]:
    if bucket == "day":
        keys: list[str] = []
        cursor = start
        while cursor <= end:
            keys.append(cursor.isoformat())
            cursor += timedelta(days=1)
        return keys
    keys = []
    cursor = _month_start(start)
    while cursor <= end:
        keys.append(cursor.strftime("%Y-%m"))
        cursor = _shift_months(cursor, 1)
    return keys


def _transaction_metrics(
    transactions: list[Transaction],
    *,
    start: date,
    end: date,
    bucket: str,
    recurring_keys: set[tuple[int, str]],
) -> dict[str, object]:
    income = Decimal("0")
    spending = Decimal("0")
    recurring_spending = Decimal("0")
    discretionary_spending = Decimal("0")
    categories: dict[tuple[int | None, str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    category_counts: dict[tuple[int | None, str, str], int] = defaultdict(int)
    merchants: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    merchant_counts: dict[str, int] = defaultdict(int)
    merchant_categories: dict[str, str] = {}
    series: dict[str, dict[str, Decimal]] = {
        key: {"income": Decimal("0"), "spending": Decimal("0")}
        for key in _series_keys(start, end, bucket)
    }

    for transaction in transactions:
        if transaction.excluded_from_spending:
            continue
        kind = effective_kind(transaction)
        if kind == "transfer":
            continue
        key = _bucket_key(transaction.posted_date, bucket)
        if key not in series:
            continue
        if kind == "income":
            amount = transaction.amount
            income += amount
            series[key]["income"] += amount
            continue
        if kind not in {"expense", "refund"}:
            continue

        amount = -transaction.amount if kind == "expense" else -transaction.amount
        spending += amount
        series[key]["spending"] += amount
        category = effective_category(transaction)
        category_key = (
            category.id if category else None,
            category.stable_key if category else "other",
            category.name if category else "Other",
        )
        categories[category_key] += amount
        category_counts[category_key] += 1

        normalized = normalize_merchant(effective_merchant(transaction))
        recurring = bool(normalized) and (transaction.account_id, normalized.casefold()) in recurring_keys
        if recurring:
            recurring_spending += amount
        else:
            discretionary_spending += amount

        merchant = effective_merchant(transaction) or transaction.description or "Unknown merchant"
        merchant = merchant.strip()[:160]
        merchants[merchant] += amount
        merchant_counts[merchant] += 1
        merchant_categories.setdefault(merchant, category.name if category else "Other")

    return {
        "income": income,
        "spending": spending,
        "net_cash_flow": income - spending,
        "recurring_spending": recurring_spending,
        "discretionary_spending": discretionary_spending,
        "categories": categories,
        "category_counts": category_counts,
        "merchants": merchants,
        "merchant_counts": merchant_counts,
        "merchant_categories": merchant_categories,
        "series": series,
    }


def snapshot_values(db: Session, user: User) -> dict[str, object]:
    today = _local_today(user)
    month = today.strftime("%Y-%m")
    dashboard = dashboard_data(db, user, month)
    budget = month_budget_view(db, user, month)
    goals = list_goals(db, user)
    debts = list_debts(db, user)
    forecast = forecast_view(db, user)
    horizon_rows = cast(list[dict[str, object]], forecast["horizons"])
    horizons = {int(row["days"]): row for row in horizon_rows}

    def projected(days: int) -> Decimal:
        row = horizons.get(days)
        return _decimal(row["projected_balance"]) if row else Decimal("0")

    summary = cast(dict[str, object], dashboard["summary"])
    return {
        "snapshot_date": today,
        "currency": user.settings.currency,
        "net_worth": _decimal(summary["net_worth"]),
        "cash_available": _decimal(budget["cash_available"]),
        "planned_income": _decimal(budget["planned_income"]),
        "actual_income": _decimal(budget["actual_income"]),
        "budgeted": _decimal(budget["budgeted"]),
        "spent": _decimal(budget["spent"]),
        "safe_to_spend": _decimal(budget["safe_to_spend"]),
        "planning_commitments": _decimal(budget["planning_commitments"]),
        "goal_reserves": _decimal(budget["goal_reserves"]),
        "total_goal_target": _decimal(goals["total_target"]),
        "total_goal_current": _decimal(goals["total_current"]),
        "monthly_goal_contributions": _decimal(goals["monthly_contributions"]),
        "total_debt": _decimal(debts["total_balance"]),
        "planned_monthly_debt_payment": _decimal(debts["planned_monthly_payment"]),
        "reserve_balance": _decimal(forecast["reserve_balance"]),
        "projected_30_day": projected(30),
        "projected_60_day": projected(60),
        "projected_90_day": projected(90),
        "planned_debt_free_date": cast(date | None, debts["planned_debt_free_date"]),
    }


def capture_snapshot(db: Session, user: User) -> FinancialSnapshot:
    values = snapshot_values(db, user)
    snapshot_date = cast(date, values["snapshot_date"])
    row = db.scalar(
        select(FinancialSnapshot).where(
            FinancialSnapshot.user_id == user.id,
            FinancialSnapshot.snapshot_date == snapshot_date,
        )
    )
    if row is None:
        row = FinancialSnapshot(user_id=user.id, snapshot_date=snapshot_date)
        db.add(row)
    for field, value in values.items():
        if field == "snapshot_date":
            continue
        setattr(row, field, value)
    db.flush()
    return row


def capture_all_snapshots(db: Session) -> dict[str, int]:
    user_ids = list(db.scalars(select(User.id).order_by(User.id)).all())
    succeeded = 0
    failed = 0
    for user_id in user_ids:
        try:
            user = db.scalar(
                select(User).options(selectinload(User.settings)).where(User.id == user_id)
            )
            if user is None or user.settings is None:
                continue
            capture_snapshot(db, user)
            db.commit()
            succeeded += 1
        except Exception:
            db.rollback()
            failed += 1
    return {"succeeded": succeeded, "failed": failed}


def _view_from_values(values: dict[str, object], *, captured_at: datetime) -> dict[str, object]:
    return {
        "snapshot_date": values["snapshot_date"],
        "currency": values["currency"],
        "net_worth": money(cast(Decimal, values["net_worth"])),
        "cash_available": money(cast(Decimal, values["cash_available"])),
        "planned_income": money(cast(Decimal, values["planned_income"])),
        "actual_income": money(cast(Decimal, values["actual_income"])),
        "budgeted": money(cast(Decimal, values["budgeted"])),
        "spent": money(cast(Decimal, values["spent"])),
        "safe_to_spend": money(cast(Decimal, values["safe_to_spend"])),
        "planning_commitments": money(cast(Decimal, values["planning_commitments"])),
        "goal_reserves": money(cast(Decimal, values["goal_reserves"])),
        "total_goal_target": money(cast(Decimal, values["total_goal_target"])),
        "total_goal_current": money(cast(Decimal, values["total_goal_current"])),
        "monthly_goal_contributions": money(cast(Decimal, values["monthly_goal_contributions"])),
        "total_debt": money(cast(Decimal, values["total_debt"])),
        "planned_monthly_debt_payment": money(
            cast(Decimal, values["planned_monthly_debt_payment"])
        ),
        "reserve_balance": money(cast(Decimal, values["reserve_balance"])),
        "projected_30_day": money(cast(Decimal, values["projected_30_day"])),
        "projected_60_day": money(cast(Decimal, values["projected_60_day"])),
        "projected_90_day": money(cast(Decimal, values["projected_90_day"])),
        "planned_debt_free_date": values["planned_debt_free_date"],
        "captured_at": captured_at,
    }


def snapshot_view(row: FinancialSnapshot) -> dict[str, object]:
    values: dict[str, object] = {
        "snapshot_date": row.snapshot_date,
        "currency": row.currency,
        "net_worth": row.net_worth,
        "cash_available": row.cash_available,
        "planned_income": row.planned_income,
        "actual_income": row.actual_income,
        "budgeted": row.budgeted,
        "spent": row.spent,
        "safe_to_spend": row.safe_to_spend,
        "planning_commitments": row.planning_commitments,
        "goal_reserves": row.goal_reserves,
        "total_goal_target": row.total_goal_target,
        "total_goal_current": row.total_goal_current,
        "monthly_goal_contributions": row.monthly_goal_contributions,
        "total_debt": row.total_debt,
        "planned_monthly_debt_payment": row.planned_monthly_debt_payment,
        "reserve_balance": row.reserve_balance,
        "projected_30_day": row.projected_30_day,
        "projected_60_day": row.projected_60_day,
        "projected_90_day": row.projected_90_day,
        "planned_debt_free_date": row.planned_debt_free_date,
    }
    return _view_from_values(values, captured_at=row.updated_at)


def reports_overview(db: Session, user: User, days: int) -> dict[str, object]:
    current_values = snapshot_values(db, user)
    today = cast(date, current_values["snapshot_date"])
    start = today - timedelta(days=max(days - 1, 0))
    rows = list(
        db.scalars(
            select(FinancialSnapshot)
            .where(
                FinancialSnapshot.user_id == user.id,
                FinancialSnapshot.snapshot_date >= start,
                FinancialSnapshot.snapshot_date <= today,
            )
            .order_by(FinancialSnapshot.snapshot_date)
        ).all()
    )
    now = utc_now()
    return {
        "generated_at": now,
        "currency": user.settings.currency,
        "current": _view_from_values(current_values, captured_at=now),
        "history": [snapshot_view(row) for row in rows],
    }


def reports_spending(db: Session, user: User, range_key: ReportRange) -> dict[str, object]:
    bounds = _range_bounds(user, range_key)
    start = cast(date, bounds["start"])
    end = cast(date, bounds["end"])
    previous_start = cast(date, bounds["previous_start"])
    previous_end = cast(date, bounds["previous_end"])
    bucket = cast(str, bounds["bucket"])

    recurring_keys = {
        (stream.account_id, stream.merchant_key.casefold())
        for stream in db.scalars(
            select(RecurringStream).where(
                RecurringStream.user_id == user.id,
                RecurringStream.active.is_(True),
                RecurringStream.kind == "expense",
            )
        ).all()
    }
    current = _transaction_metrics(
        _report_transactions(db, user, start, end),
        start=start,
        end=end,
        bucket=bucket,
        recurring_keys=recurring_keys,
    )
    previous = _transaction_metrics(
        _report_transactions(db, user, previous_start, previous_end),
        start=previous_start,
        end=previous_end,
        bucket=bucket,
        recurring_keys=recurring_keys,
    )

    current_categories = cast(dict[tuple[int | None, str, str], Decimal], current["categories"])
    previous_categories = cast(dict[tuple[int | None, str, str], Decimal], previous["categories"])
    category_counts = cast(dict[tuple[int | None, str, str], int], current["category_counts"])
    category_rows: list[dict[str, object]] = []
    for category_key in set(current_categories) | set(previous_categories):
        amount = current_categories.get(category_key, Decimal("0"))
        prior = previous_categories.get(category_key, Decimal("0"))
        if amount == 0 and prior == 0:
            continue
        category_id, stable_key, name = category_key
        category_rows.append(
            {
                "category_id": category_id,
                "key": stable_key,
                "name": name,
                "amount": money(amount),
                "previous_amount": money(prior),
                "change_amount": money(amount - prior),
                "change_pct": money(_pct_change(amount, prior)),
                "transaction_count": category_counts.get(category_key, 0),
            }
        )
    category_rows.sort(key=lambda row: -_decimal(row["amount"]))

    merchant_amounts = cast(dict[str, Decimal], current["merchants"])
    merchant_counts = cast(dict[str, int], current["merchant_counts"])
    merchant_categories = cast(dict[str, str], current["merchant_categories"])
    merchant_rows = [
        {
            "name": name,
            "category": merchant_categories.get(name, "Other"),
            "amount": money(amount),
            "transaction_count": merchant_counts.get(name, 0),
        }
        for name, amount in sorted(merchant_amounts.items(), key=lambda item: (-item[1], item[0].casefold()))
        if amount > 0
    ][:10]

    series_rows = []
    current_series = cast(dict[str, dict[str, Decimal]], current["series"])
    for period, values in current_series.items():
        income = values["income"]
        spending = values["spending"]
        series_rows.append(
            {
                "period": period,
                "income": money(income),
                "spending": money(spending),
                "net_cash_flow": money(income - spending),
            }
        )

    today = _local_today(user)
    current_month_start = date(today.year, today.month, 1)
    current_month_transactions = _report_transactions(db, user, current_month_start, today)
    current_month_metrics = _transaction_metrics(
        current_month_transactions,
        start=current_month_start,
        end=today,
        bucket="day",
        recurring_keys=recurring_keys,
    )
    elapsed_days = max(today.day, 1)
    month_days = calendar.monthrange(today.year, today.month)[1]
    current_month_spending = cast(Decimal, current_month_metrics["spending"])
    projected_month_spending = current_month_spending / Decimal(elapsed_days) * Decimal(month_days)

    current_spending = cast(Decimal, current["spending"])
    previous_spending = cast(Decimal, previous["spending"])
    current_income = cast(Decimal, current["income"])
    current_net = cast(Decimal, current["net_cash_flow"])
    previous_income = cast(Decimal, previous["income"])
    previous_net = cast(Decimal, previous["net_cash_flow"])
    recurring_spending = cast(Decimal, current["recurring_spending"])
    discretionary_spending = cast(Decimal, current["discretionary_spending"])

    return {
        "generated_at": utc_now(),
        "currency": user.settings.currency,
        "range": bounds,
        "summary": {
            "income": money(current_income),
            "spending": money(current_spending),
            "net_cash_flow": money(current_net),
            "savings_rate": money(current_net / current_income * Decimal("100")) if current_income > 0 else None,
            "spending_change_amount": money(current_spending - previous_spending),
            "spending_change_pct": money(_pct_change(current_spending, previous_spending)),
            "income_change_pct": money(_pct_change(current_income, previous_income)),
            "net_cash_flow_change_pct": money(_pct_change(current_net, previous_net)),
            "current_month_spending": money(current_month_spending),
            "projected_month_spending": money(projected_month_spending),
        },
        "series": series_rows,
        "categories": category_rows,
        "top_merchants": merchant_rows,
        "recurring": {
            "recurring": money(recurring_spending),
            "discretionary": money(discretionary_spending),
            "total": money(recurring_spending + discretionary_spending),
        },
    }


def reports_budget(db: Session, user: User, range_key: ReportRange) -> dict[str, object]:
    bounds = _range_bounds(user, range_key)
    today = _local_today(user)
    start = cast(date, bounds["start"])
    first_month = _month_start(start)
    current_month = _month_start(today)

    months: list[dict[str, object]] = []
    cursor = first_month
    while cursor <= current_month:
        view = month_budget_view(db, user, cursor.strftime("%Y-%m"))
        budgeted = _decimal(view["budgeted"])
        spent = _decimal(view["spent"])
        months.append(
            {
                "month": cursor.strftime("%Y-%m"),
                "source": view["source"],
                "planned_income": view["planned_income"],
                "actual_income": view["actual_income"],
                "budgeted": view["budgeted"],
                "spent": view["spent"],
                "remaining": view["remaining"],
                "utilization_pct": money(spent / budgeted * Decimal("100")) if budgeted > 0 else None,
            }
        )
        cursor = _shift_months(cursor, 1)

    year = year_budget_view(db, user, today.year)
    ytd_planned = _decimal(year["ytd_planned_income"])
    actual_income = _decimal(year["actual_income"])
    budgeted = _decimal(year["budgeted"])
    spent = _decimal(year["spent"])
    elapsed_days = max((today - date(today.year, 1, 1)).days + 1, 1)
    year_days = 366 if calendar.isleap(today.year) else 365
    projected_year_end = spent / Decimal(elapsed_days) * Decimal(year_days)

    categories = []
    for row in cast(list[dict[str, object]], year["categories"]):
        category = cast(dict[str, object], row["category"])
        planned = _decimal(row["planned_amount"])
        ytd_plan = _decimal(row["ytd_planned_amount"])
        category_spent = _decimal(row["spent_amount"])
        categories.append(
            {
                "category_id": category["id"],
                "key": category["key"],
                "name": category["name"],
                "planned_amount": row["planned_amount"],
                "ytd_planned_amount": row["ytd_planned_amount"],
                "spent_amount": row["spent_amount"],
                "remaining_amount": row["remaining_amount"],
                "percent_used": row["percent_used"],
                "ytd_variance": money(ytd_plan - category_spent),
                "annual_variance": money(planned - category_spent),
            }
        )
    categories.sort(key=lambda row: -_decimal(row["spent_amount"]))

    return {
        "generated_at": utc_now(),
        "currency": user.settings.currency,
        "range": bounds,
        "year": today.year,
        "has_annual_plan": year["has_annual_plan"],
        "summary": {
            "planned_income": year["planned_income"],
            "ytd_planned_income": year["ytd_planned_income"],
            "actual_income": year["actual_income"],
            "budgeted": year["budgeted"],
            "spent": year["spent"],
            "remaining": year["remaining"],
            "unallocated": year["unallocated"],
            "income_variance": money(actual_income - ytd_planned),
            "budget_utilization_pct": money(spent / budgeted * Decimal("100")) if budgeted > 0 else None,
            "projected_year_end_spend": money(projected_year_end),
        },
        "months": months,
        "categories": categories,
    }
