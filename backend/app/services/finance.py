from __future__ import annotations

import calendar
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ApiError
from app.core.security import utc_now
from app.models import Account, Transaction, User
from app.services.transaction_intelligence import effective_category, effective_kind, effective_merchant
from app.services.views import account_view, money, transaction_view


def month_bounds(user: User, month: str | None) -> tuple[str, date, date]:
    if month is None:
        local_today = datetime.now(ZoneInfo(user.settings.timezone)).date()
        year, month_number = local_today.year, local_today.month
    else:
        try:
            parsed = datetime.strptime(month, "%Y-%m")
            if parsed.strftime("%Y-%m") != month:
                raise ValueError
            year, month_number = parsed.year, parsed.month
        except ValueError as exc:
            raise ApiError(422, "invalid_month", "Month must use YYYY-MM format") from exc
    start = date(year, month_number, 1)
    end = date(year, month_number, calendar.monthrange(year, month_number)[1])
    return f"{year:04d}-{month_number:02d}", start, end


def dashboard_data(db: Session, user: User, month: str | None) -> dict[str, object]:
    period, start, end = month_bounds(user, month)
    currency = user.settings.currency
    accounts = db.scalars(
        select(Account)
        .options(joinedload(Account.institution))
        .where(Account.user_id == user.id)
        .order_by(Account.name, Account.id)
    ).all()
    included_accounts = [account for account in accounts if account.currency == currency]
    included_ids = [account.id for account in included_accounts]

    transactions: list[Transaction]
    if included_ids:
        transactions = list(
            db.scalars(
                select(Transaction)
                .options(
                    joinedload(Transaction.account),
                    joinedload(Transaction.category),
                    joinedload(Transaction.user_category_override),
                )
                .where(
                    Transaction.user_id == user.id,
                    Transaction.account_id.in_(included_ids),
                    Transaction.posted_date >= start,
                    Transaction.posted_date <= end,
                )
                .order_by(Transaction.posted_date, Transaction.id)
            ).all()
        )
    else:
        transactions = []

    income = Decimal("0")
    spending = Decimal("0")
    daily: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    categories: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for transaction in transactions:
        amount = transaction.amount
        kind = effective_kind(transaction)
        category = effective_category(transaction)
        if kind == "transfer" or transaction.excluded_from_spending:
            continue
        daily[transaction.posted_date] += amount
        if kind == "income":
            income += amount
        elif kind == "expense":
            expense = -amount
            spending += expense
            key = (
                category.stable_key if category else "other",
                category.name if category else "Other",
            )
            categories[key] += expense
        elif kind == "refund":
            spending -= amount
            key = (
                category.stable_key if category else "other",
                category.name if category else "Other",
            )
            categories[key] -= amount

    net_cash_flow = income - spending
    savings_rate = (net_cash_flow / income * Decimal("100")) if income > 0 else None
    net_worth = sum((account.current_balance for account in included_accounts), Decimal("0"))
    cash_available = sum(
        (
            account.available_balance
            if account.available_balance is not None
            else account.current_balance
            for account in included_accounts
            if account.account_type == "depository"
        ),
        Decimal("0"),
    )

    series: list[dict[str, object]] = []
    cursor = start
    while cursor <= end:
        series.append({"date": cursor, "amount": money(daily[cursor])})
        cursor += timedelta(days=1)

    recent = db.scalars(
        select(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.category),
            joinedload(Transaction.user_category_override),
        )
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.posted_date.desc(), Transaction.id.desc())
        .limit(8)
    ).all()

    return {
        "period": {"month": period, "start": start, "end": end},
        "currency": currency,
        "as_of": utc_now(),
        "summary": {
            "net_worth": money(net_worth),
            "cash_available": money(cash_available),
            "income": money(income),
            "spending": money(spending),
            "net_cash_flow": money(net_cash_flow),
            "savings_rate": money(savings_rate),
        },
        "spending_by_category": [
            {"key": key, "name": name, "amount": money(amount)}
            for (key, name), amount in sorted(
                categories.items(), key=lambda item: (-item[1], item[0][1])
            )
        ],
        "daily_cash_flow": series,
        "accounts": [account_view(account) for account in accounts],
        "recent_transactions": [transaction_view(item) for item in recent],
        "excluded_currencies": sorted(
            {account.currency for account in accounts if account.currency != currency}
        ),
    }


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def transaction_page(
    db: Session,
    user: User,
    *,
    page: int,
    page_size: int,
    start_date: date | None,
    end_date: date | None,
    account_id: int | None,
    category_id: int | None,
    search: str | None,
    min_amount: Decimal | None,
    max_amount: Decimal | None,
    kind: str | None,
    pending: bool | None,
    sort: str,
    direction: str,
) -> dict[str, object]:
    if start_date and end_date and start_date > end_date:
        raise ApiError(422, "invalid_date_range", "Start date must not be after end date")
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise ApiError(422, "invalid_amount_range", "Minimum amount must not exceed maximum amount")

    conditions = [Transaction.user_id == user.id]
    if start_date:
        conditions.append(Transaction.posted_date >= start_date)
    if end_date:
        conditions.append(Transaction.posted_date <= end_date)
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    if category_id is not None:
        conditions.append(
            or_(
                Transaction.user_category_override_id == category_id,
                (
                    Transaction.user_category_override_id.is_(None)
                    & (Transaction.category_id == category_id)
                ),
            )
        )
    if min_amount is not None:
        conditions.append(Transaction.amount >= min_amount)
    if max_amount is not None:
        conditions.append(Transaction.amount <= max_amount)
    if kind:
        conditions.append(
            or_(
                Transaction.user_kind_override == kind,
                (Transaction.user_kind_override.is_(None) & (Transaction.kind == kind)),
            )
        )
    if pending is not None:
        conditions.append(Transaction.pending.is_(pending))
    if search:
        term = f"%{escape_like(search.casefold())}%"
        conditions.append(
            or_(
                func.lower(Transaction.display_merchant).like(term, escape="\\"),
                func.lower(Transaction.merchant).like(term, escape="\\"),
                func.lower(Transaction.description).like(term, escape="\\"),
            )
        )

    total = db.scalar(select(func.count(Transaction.id)).where(*conditions)) or 0
    sort_columns = {
        "date": Transaction.posted_date,
        "amount": Transaction.amount,
        "merchant": func.coalesce(Transaction.display_merchant, Transaction.merchant),
        "description": Transaction.description,
    }
    sort_column = sort_columns[sort]
    order = sort_column.asc() if direction == "asc" else sort_column.desc()
    statement: Select[tuple[Transaction]] = (
        select(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.category),
            joinedload(Transaction.user_category_override),
        )
        .where(*conditions)
        .order_by(order, Transaction.id.asc() if direction == "asc" else Transaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = db.scalars(statement).all()
    return {
        "items": [transaction_view(item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }
