from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Account, Debt, ForecastAssumptions, RecurringStream, Transaction, User
from app.services.transaction_intelligence import (
    effective_category,
    effective_kind,
    effective_merchant,
    normalize_merchant,
)
from app.services.views import money

CADENCE_DAYS = {
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
    "quarterly": 91,
    "annual": 365,
}

CalendarEventKind = Literal["income", "expense", "subscription", "debt", "savings", "refund"]
CalendarEventStatus = Literal["observed", "pending", "expected", "planned"]


def _today(user: User) -> date:
    return datetime.now(ZoneInfo(user.settings.timezone)).date()


def _month_bounds(value: str | None, today: date) -> tuple[date, date, str]:
    if value is None:
        year, month = today.year, today.month
    else:
        try:
            year_text, month_text = value.split("-", 1)
            year, month = int(year_text), int(month_text)
            if year < 2000 or year > 2200 or month < 1 or month > 12:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("month must use YYYY-MM") from exc
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    return start, end, f"{year:04d}-{month:02d}"


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
    return sum(
        (
            account.available_balance
            if account.available_balance is not None
            else account.current_balance
            for account in accounts
        ),
        Decimal("0"),
    )


def _reserve_balance(db: Session, user: User) -> Decimal:
    row = db.scalar(select(ForecastAssumptions).where(ForecastAssumptions.user_id == user.id))
    return row.reserve_balance if row is not None else Decimal("0")


def _stream_key(transaction: Transaction) -> tuple[int, str, str] | None:
    kind = effective_kind(transaction)
    if kind not in {"income", "expense"}:
        return None
    merchant = normalize_merchant(effective_merchant(transaction))
    if not merchant:
        return None
    return transaction.account_id, merchant.casefold(), kind


def _transaction_context(
    db: Session,
    user: User,
    *,
    since: date,
) -> tuple[dict[tuple[int, str, str], Transaction], list[Transaction]]:
    rows = list(
        db.scalars(
            select(Transaction)
            .options(
                joinedload(Transaction.account),
                joinedload(Transaction.category),
                joinedload(Transaction.user_category_override),
            )
            .where(Transaction.user_id == user.id, Transaction.posted_date >= since)
            .order_by(Transaction.posted_date.desc(), Transaction.id.desc())
        ).all()
    )
    latest: dict[tuple[int, str, str], Transaction] = {}
    for row in rows:
        if row.pending:
            continue
        key = _stream_key(row)
        if key is not None and key not in latest:
            latest[key] = row
    return latest, rows


def _event_kind(kind: str, category_key: str | None) -> CalendarEventKind:
    if kind == "income":
        return "income"
    if kind == "refund":
        return "refund"
    if category_key == "subscriptions":
        return "subscription"
    if category_key == "debt_payments":
        return "debt"
    if category_key == "savings":
        return "savings"
    return "expense"


def _filters(
    *,
    account_id: int | None,
    category_id: int | None,
    kind: str | None,
    search: str | None,
    on_date: date | None = None,
) -> dict[str, object]:
    return {
        "start_date": on_date,
        "end_date": on_date,
        "account_id": account_id,
        "category_id": category_id,
        "kind": kind if kind in {"income", "expense", "refund", "transfer"} else None,
        "search": search,
    }


def _ask_prompt(name: str, amount: Decimal, event_date: date, status: CalendarEventStatus, currency: str) -> str:
    verb = {
        "observed": "posted",
        "pending": "is pending",
        "expected": "is expected",
        "planned": "is planned",
    }[status]
    return (
        f"{name} {verb} for {currency} {money(abs(amount))} on {event_date.isoformat()}. "
        "Explain how this affects my cash flow and whether I should change anything."
    )


def _stream_event(
    stream: RecurringStream,
    *,
    event_date: date,
    status: CalendarEventStatus,
    context: Transaction | None,
    user: User,
    sequence: int,
) -> dict[str, object]:
    category = effective_category(context) if context is not None else None
    category_key = category.stable_key if category is not None else None
    category_id = category.id if category is not None else None
    kind = _event_kind(stream.kind, category_key)
    amount = abs(stream.average_amount)
    impact = amount if stream.kind == "income" else -amount
    search = stream.display_name
    return {
        "id": f"stream:{stream.id}:{event_date.isoformat()}:{sequence}",
        "date": event_date,
        "name": stream.display_name,
        "kind": kind,
        "status": status,
        "amount": money(amount),
        "impact": money(impact),
        "cadence": stream.cadence,
        "price_change_pct": money(stream.price_change_pct) if stream.price_change_pct is not None else None,
        "stream_id": stream.id,
        "transaction_id": None,
        "account": {
            "id": stream.account.id,
            "name": stream.account.name,
            "currency": stream.account.currency,
        },
        "category": (
            {"id": category.id, "key": category.stable_key, "name": category.name}
            if category is not None
            else None
        ),
        "source_detail": f"Detected {stream.cadence} pattern",
        "filters": _filters(
            account_id=stream.account_id,
            category_id=category_id,
            kind=stream.kind,
            search=search,
        ),
        "ask_prompt": _ask_prompt(stream.display_name, impact, event_date, status, user.settings.currency),
    }


def _transaction_event(
    transaction: Transaction,
    *,
    status: CalendarEventStatus,
    user: User,
) -> dict[str, object] | None:
    kind_name = effective_kind(transaction)
    if kind_name == "transfer" or transaction.excluded_from_spending:
        return None
    if kind_name not in {"income", "expense", "refund"}:
        return None
    category = effective_category(transaction)
    category_key = category.stable_key if category is not None else None
    kind = _event_kind(kind_name, category_key)
    amount = abs(transaction.amount)
    impact = amount if kind_name in {"income", "refund"} else -amount
    name = normalize_merchant(effective_merchant(transaction)) or transaction.description
    return {
        "id": f"transaction:{transaction.id}",
        "date": transaction.posted_date,
        "name": name,
        "kind": kind,
        "status": status,
        "amount": money(amount),
        "impact": money(impact),
        "cadence": None,
        "price_change_pct": None,
        "stream_id": None,
        "transaction_id": transaction.id,
        "account": {
            "id": transaction.account.id,
            "name": transaction.account.name,
            "currency": transaction.account.currency,
        },
        "category": (
            {"id": category.id, "key": category.stable_key, "name": category.name}
            if category is not None
            else None
        ),
        "source_detail": "Pending transaction" if status == "pending" else "Posted recurring activity",
        "filters": _filters(
            account_id=transaction.account_id,
            category_id=category.id if category is not None else None,
            kind=kind_name,
            search=name,
            on_date=transaction.posted_date,
        ),
        "ask_prompt": _ask_prompt(name, impact, transaction.posted_date, status, user.settings.currency),
    }


def _recurring_occurrences(stream: RecurringStream, start: date, end: date) -> list[date]:
    step = timedelta(days=CADENCE_DAYS[stream.cadence])
    current = stream.next_expected_date
    while current < start:
        current += step
    result: list[date] = []
    while current <= end:
        result.append(current)
        current += step
    return result


def _debt_occurrences(debt: Debt, start: date, end: date) -> list[date]:
    if debt.due_day is None:
        return []
    result: list[date] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        day = min(debt.due_day, calendar.monthrange(cursor.year, cursor.month)[1])
        due = date(cursor.year, cursor.month, day)
        if start <= due <= end:
            result.append(due)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return result


def _future_events(
    db: Session,
    user: User,
    streams: list[RecurringStream],
    latest_context: dict[tuple[int, str, str], Transaction],
    all_transactions: list[Transaction],
    start: date,
    end: date,
) -> list[dict[str, object]]:
    pending_rows = [
        row
        for row in all_transactions
        if row.pending and start <= row.posted_date <= end
    ]
    pending_events = [
        event
        for row in pending_rows
        if (event := _transaction_event(row, status="pending", user=user)) is not None
    ]

    pending_match: dict[tuple[int, str, str], list[date]] = defaultdict(list)
    for row in pending_rows:
        key = _stream_key(row)
        if key is not None:
            pending_match[key].append(row.posted_date)

    events: list[dict[str, object]] = list(pending_events)
    for stream in streams:
        key = (stream.account_id, stream.merchant_key.casefold(), stream.kind)
        context = latest_context.get(key)
        for index, event_date in enumerate(_recurring_occurrences(stream, start, end)):
            if any(abs((pending_date - event_date).days) <= 4 for pending_date in pending_match.get(key, [])):
                continue
            events.append(
                _stream_event(
                    stream,
                    event_date=event_date,
                    status="expected",
                    context=context,
                    user=user,
                    sequence=index,
                )
            )

    debts = list(
        db.scalars(
            select(Debt)
            .options(joinedload(Debt.linked_account))
            .where(Debt.user_id == user.id, Debt.active.is_(True), Debt.due_day.is_not(None))
            .order_by(Debt.due_day, Debt.id)
        ).all()
    )
    for debt in debts:
        payment = debt.minimum_payment + debt.extra_payment
        if payment <= 0:
            continue
        for due in _debt_occurrences(debt, start, end):
            duplicate = False
            for event in events:
                if cast(date, event["date"]) != due:
                    continue
                if cast(str, event["kind"]) != "debt":
                    continue
                event_amount = Decimal(cast(str, event["amount"]))
                if abs(event_amount - payment) <= max(payment * Decimal("0.05"), Decimal("1")):
                    duplicate = True
                    break
            if duplicate:
                continue
            events.append(
                {
                    "id": f"debt:{debt.id}:{due.isoformat()}",
                    "date": due,
                    "name": debt.name,
                    "kind": "debt",
                    "status": "planned",
                    "amount": money(payment),
                    "impact": money(-payment),
                    "cadence": "monthly",
                    "price_change_pct": None,
                    "stream_id": None,
                    "transaction_id": None,
                    "account": (
                        {
                            "id": debt.linked_account.id,
                            "name": debt.linked_account.name,
                            "currency": debt.linked_account.currency,
                        }
                        if debt.linked_account is not None
                        else None
                    ),
                    "category": None,
                    "source_detail": "Planned debt payment",
                    "filters": _filters(
                        account_id=debt.linked_account_id,
                        category_id=None,
                        kind="expense",
                        search=None,
                    ),
                    "ask_prompt": _ask_prompt(debt.name, -payment, due, "planned", user.settings.currency),
                }
            )
    events.sort(key=lambda row: (cast(date, row["date"]), -Decimal(cast(str, row["impact"])), cast(str, row["name"])))
    return events


def _observed_events(
    user: User,
    streams: list[RecurringStream],
    rows: list[Transaction],
    start: date,
    end: date,
) -> list[dict[str, object]]:
    stream_keys = {(stream.account_id, stream.merchant_key.casefold(), stream.kind) for stream in streams}
    events: list[dict[str, object]] = []
    for row in rows:
        if row.pending or row.posted_date < start or row.posted_date > end:
            continue
        key = _stream_key(row)
        if key not in stream_keys:
            continue
        event = _transaction_event(row, status="observed", user=user)
        if event is not None:
            events.append(event)
    events.sort(key=lambda row: (cast(date, row["date"]), cast(str, row["name"])))
    return events


def _projection(
    *,
    today: date,
    month_start: date,
    month_end: date,
    current_cash: Decimal,
    reserve: Decimal,
    future_events: list[dict[str, object]],
) -> tuple[list[dict[str, object]], Decimal | None, Decimal | None, date | None, Decimal | None]:
    if month_end < today:
        return [], None, None, None, None

    by_date: dict[date, list[dict[str, object]]] = defaultdict(list)
    for event in future_events:
        by_date[cast(date, event["date"])].append(event)

    balance = current_cash
    projected_start: Decimal | None = current_cash if month_start <= today <= month_end else None
    if month_start > today:
        cursor = today
        while cursor < month_start:
            for event in by_date.get(cursor, []):
                if event["status"] != "pending":
                    balance += Decimal(cast(str, event["impact"]))
            cursor += timedelta(days=1)
        projected_start = balance

    projection_start = max(today, month_start)
    points: list[dict[str, object]] = []
    low_balance = balance
    low_date = projection_start
    cursor = projection_start
    while cursor <= month_end:
        delta = sum(
            (
                Decimal(cast(str, row["impact"]))
                for row in by_date.get(cursor, [])
                if row["status"] != "pending"
            ),
            Decimal("0"),
        )
        balance += delta
        if balance < low_balance:
            low_balance = balance
            low_date = cursor
        points.append(
            {
                "date": cursor,
                "balance": money(balance),
                "delta": money(delta),
                "event_count": len(by_date.get(cursor, [])),
                "below_reserve": balance < reserve,
            }
        )
        cursor += timedelta(days=1)
    return points, projected_start, balance, low_date, low_balance


def financial_calendar_view(db: Session, user: User, month: str | None = None) -> dict[str, object]:
    today = _today(user)
    month_start, month_end, month_key = _month_bounds(month, today)
    currency = user.settings.currency
    current_cash = _cash_available(db, user)
    reserve = _reserve_balance(db, user)

    streams = list(
        db.scalars(
            select(RecurringStream)
            .options(joinedload(RecurringStream.account))
            .where(RecurringStream.user_id == user.id, RecurringStream.active.is_(True))
            .order_by(RecurringStream.next_expected_date, RecurringStream.display_name)
        ).all()
    )
    context_since = min(month_start, today) - timedelta(days=400)
    latest_context, transactions = _transaction_context(db, user, since=context_since)

    selected_observed = _observed_events(user, streams, transactions, month_start, min(month_end, today))
    selected_future_start = max(today, month_start)
    selected_future = (
        _future_events(db, user, streams, latest_context, transactions, selected_future_start, month_end)
        if selected_future_start <= month_end
        else []
    )
    selected_events = selected_observed + selected_future
    selected_events.sort(key=lambda row: (cast(date, row["date"]), cast(str, row["status"]) != "observed", cast(str, row["name"])))

    projection_future = (
        _future_events(db, user, streams, latest_context, transactions, today, month_end)
        if month_end >= today
        else []
    )
    points, projected_start, projected_end, low_date, low_balance = _projection(
        today=today,
        month_start=month_start,
        month_end=month_end,
        current_cash=current_cash,
        reserve=reserve,
        future_events=projection_future,
    )

    expected_inflow = sum(
        (
            Decimal(cast(str, row["impact"]))
            for row in selected_future
            if row["status"] != "pending" and Decimal(cast(str, row["impact"])) > 0
        ),
        Decimal("0"),
    )
    expected_outflow = sum(
        (
            -Decimal(cast(str, row["impact"]))
            for row in selected_future
            if row["status"] != "pending" and Decimal(cast(str, row["impact"])) < 0
        ),
        Decimal("0"),
    )
    observed_count = sum(1 for row in selected_events if row["status"] == "observed")
    expected_count = len(selected_events) - observed_count

    if projected_end is None or low_balance is None:
        status = "historical"
    elif low_balance < Decimal("0"):
        status = "low_cash"
    elif low_balance < reserve:
        status = "attention"
    else:
        status = "healthy"

    monthly_inflow = Decimal("0")
    monthly_outflow = Decimal("0")
    monthly_factors = {
        "weekly": Decimal("4.345"),
        "biweekly": Decimal("2.1725"),
        "monthly": Decimal("1"),
        "quarterly": Decimal("0.333333"),
        "annual": Decimal("0.083333"),
    }
    for stream in streams:
        normalized = stream.average_amount * monthly_factors[stream.cadence]
        if stream.kind == "income":
            monthly_inflow += normalized
        else:
            monthly_outflow += normalized

    return {
        "generated_at": datetime.now(ZoneInfo(user.settings.timezone)),
        "currency": currency,
        "period": {
            "month": month_key,
            "start": month_start,
            "end": month_end,
            "today": today,
            "label": month_start.strftime("%B %Y"),
            "projection_available": month_end >= today,
            "projection_start": max(today, month_start) if month_end >= today else None,
        },
        "summary": {
            "cash_available_now": money(current_cash),
            "projected_month_start": money(projected_start) if projected_start is not None else None,
            "expected_inflow": money(expected_inflow),
            "expected_outflow": money(expected_outflow),
            "projected_month_end": money(projected_end) if projected_end is not None else None,
            "lowest_projected_balance": money(low_balance) if low_balance is not None else None,
            "lowest_balance_date": low_date,
            "reserve_balance": money(reserve),
            "status": status,
            "observed_events": observed_count,
            "expected_events": expected_count,
        },
        "recurring": {
            "detected_streams": len(streams),
            "monthly_inflow_estimate": money(monthly_inflow),
            "monthly_outflow_estimate": money(monthly_outflow),
        },
        "events": selected_events,
        "projection": points,
    }
