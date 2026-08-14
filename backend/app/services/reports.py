from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import utc_now
from app.models import FinancialSnapshot, User
from app.services.budget_planning import month_budget_view
from app.services.finance import dashboard_data
from app.services.financial_planning import forecast_view, list_debts, list_goals
from app.services.views import money


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _local_today(user: User) -> date:
    return datetime.now(ZoneInfo(user.settings.timezone)).date()


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
