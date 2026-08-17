from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import pstdev
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Account, AccountBalanceSnapshot, FinancialSnapshot, Transaction, User
from app.services.financial_planning import list_debts
from app.services.transaction_intelligence import effective_category, effective_kind, effective_merchant
from app.services.views import money

TrendRange = Literal["30d", "3m", "6m", "ytd", "1y", "all"]


def _today(user: User) -> date:
    return datetime.now(ZoneInfo(user.settings.timezone)).date()


def _shift_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, zero_month = divmod(index, 12)
    return date(year, zero_month + 1, 1)


def _percent_change(current: Decimal, previous: Decimal | None) -> str | None:
    if previous is None or previous == 0:
        return None
    return money((current - previous) / abs(previous) * Decimal("100"))


def _range_bounds(db: Session, user: User, range_key: TrendRange) -> tuple[date, date, date, date, str, str]:
    today = _today(user)
    if range_key == "30d":
        start = today - timedelta(days=29)
        label = "Last 30 days"
        bucket = "day"
    elif range_key == "3m":
        start = _shift_months(date(today.year, today.month, 1), -2)
        label = "Last 3 months"
        bucket = "month"
    elif range_key == "6m":
        start = _shift_months(date(today.year, today.month, 1), -5)
        label = "Last 6 months"
        bucket = "month"
    elif range_key == "ytd":
        start = date(today.year, 1, 1)
        label = f"{today.year} year to date"
        bucket = "month"
    elif range_key == "1y":
        start = today - timedelta(days=364)
        label = "Last 12 months"
        bucket = "month"
    else:
        earliest_snapshot = db.scalar(
            select(func.min(FinancialSnapshot.snapshot_date)).where(
                FinancialSnapshot.user_id == user.id,
                FinancialSnapshot.currency == user.settings.currency,
            )
        )
        earliest_transaction = db.scalar(
            select(func.min(Transaction.posted_date)).where(Transaction.user_id == user.id)
        )
        candidates = [value for value in (earliest_snapshot, earliest_transaction) if value is not None]
        start = min(candidates) if candidates else today
        label = "All history"
        bucket = "month"
    length = max((today - start).days + 1, 1)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=length - 1)
    return start, today, previous_start, previous_end, label, bucket


def _account_totals(accounts: list[Account]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    assets = Decimal("0")
    liabilities = Decimal("0")
    cash = Decimal("0")
    for account in accounts:
        balance = account.current_balance
        if balance >= 0:
            assets += balance
        else:
            liabilities += -balance
        if account.account_type == "depository":
            cash += account.available_balance if account.available_balance is not None else balance
    return assets, liabilities, assets - liabilities, cash


def _composition(accounts: list[Account]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str, str], dict[str, object]] = {}
    for account in accounts:
        balance = account.current_balance
        if balance < 0:
            key, label, kind, value = "liabilities", "Credit & loans", "liability", -balance
        elif account.account_type == "depository":
            key, label, kind, value = "cash", "Cash & savings", "asset", balance
        elif account.account_type == "investment":
            key, label, kind, value = "investments", "Investments", "asset", balance
        else:
            key, label, kind, value = "other_assets", "Other assets", "asset", balance
        slot = buckets.setdefault((key, label, kind), {"value": Decimal("0"), "count": 0})
        slot["value"] = Decimal(str(slot["value"])) + value
        slot["count"] = int(slot["count"]) + 1
    total = sum((Decimal(str(row["value"])) for row in buckets.values()), Decimal("0"))
    rows = []
    for (key, label, kind), row in buckets.items():
        value = Decimal(str(row["value"]))
        rows.append(
            {
                "key": key,
                "label": label,
                "kind": kind,
                "value": money(value),
                "share_percent": money(value / total * Decimal("100")) if total > 0 else None,
                "account_count": int(row["count"]),
            }
        )
    return sorted(rows, key=lambda row: -Decimal(str(row["value"])))


def _current_point(accounts: list[Account], total_debt: Decimal, today: date) -> dict[str, object]:
    assets, liabilities, net_worth, cash = _account_totals(accounts)
    return {
        "date": today,
        "net_worth": money(net_worth),
        "cash_available": money(cash),
        "total_debt": money(total_debt),
        "assets": money(assets),
        "liabilities": money(liabilities),
    }


def _financial_history(
    db: Session,
    user: User,
    start: date,
    today: date,
    current: dict[str, object],
) -> list[dict[str, object]]:
    rows = list(
        db.scalars(
            select(FinancialSnapshot)
            .where(
                FinancialSnapshot.user_id == user.id,
                FinancialSnapshot.currency == user.settings.currency,
                FinancialSnapshot.snapshot_date >= start,
                FinancialSnapshot.snapshot_date <= today,
            )
            .order_by(FinancialSnapshot.snapshot_date)
        ).all()
    )
    points = [
        {
            "date": row.snapshot_date,
            "net_worth": money(row.net_worth),
            "cash_available": money(row.cash_available),
            "total_debt": money(row.total_debt),
            "assets": None,
            "liabilities": None,
        }
        for row in rows
        if row.snapshot_date != today
    ]
    points.append(current)
    return points


def _account_balance_history(
    db: Session,
    user: User,
    start: date,
    today: date,
    currency: str,
    current: dict[str, object],
) -> list[dict[str, object]]:
    rows = list(
        db.scalars(
            select(AccountBalanceSnapshot)
            .where(
                AccountBalanceSnapshot.user_id == user.id,
                AccountBalanceSnapshot.currency == currency,
                AccountBalanceSnapshot.snapshot_date >= start,
                AccountBalanceSnapshot.snapshot_date <= today,
            )
            .order_by(AccountBalanceSnapshot.snapshot_date, AccountBalanceSnapshot.account_id)
        ).all()
    )
    by_date: dict[date, tuple[Decimal, Decimal]] = defaultdict(lambda: (Decimal("0"), Decimal("0")))
    for row in rows:
        assets, liabilities = by_date[row.snapshot_date]
        if row.balance >= 0:
            assets += row.balance
        else:
            liabilities += -row.balance
        by_date[row.snapshot_date] = (assets, liabilities)
    points = [
        {
            "date": snapshot_date,
            "assets": money(assets),
            "liabilities": money(liabilities),
            "net_worth": money(assets - liabilities),
        }
        for snapshot_date, (assets, liabilities) in sorted(by_date.items())
        if snapshot_date != today
    ]
    points.append(
        {
            "date": today,
            "assets": current["assets"],
            "liabilities": current["liabilities"],
            "net_worth": current["net_worth"],
        }
    )
    return points


def _account_contributions(
    db: Session,
    user: User,
    accounts: list[Account],
    start: date,
    today: date,
) -> list[dict[str, object]]:
    history_rows = list(
        db.scalars(
            select(AccountBalanceSnapshot)
            .where(
                AccountBalanceSnapshot.user_id == user.id,
                AccountBalanceSnapshot.snapshot_date <= today,
            )
            .order_by(AccountBalanceSnapshot.account_id, AccountBalanceSnapshot.snapshot_date)
        ).all()
    )
    history_by_account: dict[int, list[AccountBalanceSnapshot]] = defaultdict(list)
    for row in history_rows:
        history_by_account[row.account_id].append(row)

    results = []
    for account in accounts:
        history = history_by_account.get(account.id, [])
        baseline = None
        for row in history:
            if row.snapshot_date <= start:
                baseline = row
            else:
                break
        start_balance = baseline.balance if baseline is not None else None
        change = account.current_balance - start_balance if start_balance is not None else None
        results.append(
            {
                "account_id": account.id,
                "name": account.name,
                "institution": account.institution.name if account.institution else None,
                "account_type": account.account_type,
                "current_balance": money(account.current_balance),
                "start_balance": money(start_balance),
                "change_amount": money(change),
                "change_percent": _percent_change(account.current_balance, start_balance),
                "history_available": baseline is not None and baseline.snapshot_date < today,
                "history_start_date": baseline.snapshot_date if baseline is not None else None,
            }
        )
    return sorted(
        results,
        key=lambda row: abs(Decimal(str(row["change_amount"]))) if row["change_amount"] is not None else Decimal("-1"),
        reverse=True,
    )


def _load_transactions(db: Session, user: User, start: date, end: date, account_ids: list[int]) -> list[Transaction]:
    if not account_ids:
        return []
    return list(
        db.scalars(
            select(Transaction)
            .options(
                joinedload(Transaction.account),
                joinedload(Transaction.category),
                joinedload(Transaction.user_category_override),
            )
            .where(
                Transaction.user_id == user.id,
                Transaction.account_id.in_(account_ids),
                Transaction.posted_date >= start,
                Transaction.posted_date <= end,
                Transaction.pending.is_(False),
            )
            .order_by(Transaction.posted_date, Transaction.id)
        ).all()
    )


def _bucket_key(value: date, bucket: str) -> str:
    return value.isoformat() if bucket == "day" else value.strftime("%Y-%m")


def _cash_flow_series(transactions: list[Transaction], bucket: str) -> list[dict[str, object]]:
    buckets: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"income": Decimal("0"), "spending": Decimal("0")})
    for tx in transactions:
        if tx.excluded_from_spending:
            continue
        kind = effective_kind(tx)
        if kind == "transfer":
            continue
        slot = buckets[_bucket_key(tx.posted_date, bucket)]
        if kind == "income":
            slot["income"] += tx.amount
        elif kind == "expense":
            slot["spending"] += -tx.amount
        elif kind == "refund":
            slot["spending"] -= tx.amount
    rows = []
    for period, row in sorted(buckets.items()):
        income = row["income"]
        spending = max(row["spending"], Decimal("0"))
        net = income - spending
        rows.append(
            {
                "period": period,
                "income": money(income),
                "spending": money(spending),
                "net_cash_flow": money(net),
                "savings_rate": money(net / income * Decimal("100")) if income > 0 else None,
            }
        )
    return rows


def _spending_categories(current: list[Transaction], previous: list[Transaction]) -> list[dict[str, object]]:
    def aggregate(rows: list[Transaction]) -> dict[tuple[str, str, int | None], Decimal]:
        result: dict[tuple[str, str, int | None], Decimal] = defaultdict(lambda: Decimal("0"))
        for tx in rows:
            if tx.excluded_from_spending or effective_kind(tx) == "transfer":
                continue
            category = effective_category(tx)
            key = category.stable_key if category else "other"
            label = category.name if category else "Other"
            category_id = category.id if category else None
            if effective_kind(tx) == "expense":
                result[(key, label, category_id)] += -tx.amount
            elif effective_kind(tx) == "refund":
                result[(key, label, category_id)] -= tx.amount
        return result

    now = aggregate(current)
    before = aggregate(previous)
    total = sum((max(value, Decimal("0")) for value in now.values()), Decimal("0"))
    rows = []
    for key_tuple, current_value in sorted(now.items(), key=lambda item: -item[1])[:8]:
        current_value = max(current_value, Decimal("0"))
        previous_value = max(before.get(key_tuple, Decimal("0")), Decimal("0"))
        change = current_value - previous_value
        key, label, category_id = key_tuple
        rows.append(
            {
                "key": key,
                "label": label,
                "category_id": category_id,
                "current": money(current_value),
                "previous": money(previous_value),
                "change_amount": money(change),
                "change_percent": _percent_change(current_value, previous_value),
                "share_percent": money(current_value / total * Decimal("100")) if total > 0 else None,
            }
        )
    return rows


def _income_sources(current: list[Transaction], previous: list[Transaction]) -> list[dict[str, object]]:
    def aggregate(rows: list[Transaction]) -> dict[str, tuple[str, Decimal]]:
        result: dict[str, tuple[str, Decimal]] = {}
        for tx in rows:
            if tx.excluded_from_spending or effective_kind(tx) != "income":
                continue
            label = effective_merchant(tx) or tx.description or "Income"
            key = label.casefold().strip()
            existing_label, existing_amount = result.get(key, (label, Decimal("0")))
            result[key] = (existing_label, existing_amount + tx.amount)
        return result

    now = aggregate(current)
    before = aggregate(previous)
    total = sum((amount for _, amount in now.values()), Decimal("0"))
    rows = []
    for key, (label, current_value) in sorted(now.items(), key=lambda item: -item[1][1])[:6]:
        previous_value = before.get(key, (label, Decimal("0")))[1]
        rows.append(
            {
                "label": label,
                "current": money(current_value),
                "previous": money(previous_value),
                "change_amount": money(current_value - previous_value),
                "change_percent": _percent_change(current_value, previous_value),
                "share_percent": money(current_value / total * Decimal("100")) if total > 0 else None,
            }
        )
    return rows


def _income_stats(transactions: list[Transaction]) -> tuple[str, str | None]:
    monthly: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for tx in transactions:
        if not tx.excluded_from_spending and effective_kind(tx) == "income":
            monthly[tx.posted_date.strftime("%Y-%m")] += tx.amount
    values = [float(value) for value in monthly.values()]
    if not values:
        return money(Decimal("0")), None
    average = Decimal(str(sum(values) / len(values)))
    variability = None
    if len(values) >= 2 and average > 0:
        variability = money(Decimal(str(pstdev(values))) / average * Decimal("100"))
    return money(average), variability


def trends_view(db: Session, user: User, range_key: TrendRange) -> dict[str, object]:
    start, today, previous_start, previous_end, label, bucket = _range_bounds(db, user, range_key)
    currency = user.settings.currency
    accounts = list(
        db.scalars(
            select(Account)
            .options(joinedload(Account.institution))
            .where(Account.user_id == user.id, Account.currency == currency)
            .order_by(Account.name, Account.id)
        ).unique().all()
    )
    assets, liabilities, net_worth, cash = _account_totals(accounts)
    debts = list_debts(db, user)
    total_planned_debt = Decimal(str(debts["total_balance"]))
    current_point = _current_point(accounts, total_planned_debt, today)
    history = _financial_history(db, user, start, today, current_point)
    balance_history = _account_balance_history(db, user, start, today, currency, current_point)

    baseline = Decimal(str(history[0]["net_worth"])) if len(history) > 1 else None
    change = net_worth - baseline if baseline is not None else Decimal("0")

    ytd_start = date(today.year, 1, 1)
    ytd_row = db.scalar(
        select(FinancialSnapshot)
        .where(
            FinancialSnapshot.user_id == user.id,
            FinancialSnapshot.currency == currency,
            FinancialSnapshot.snapshot_date >= ytd_start,
            FinancialSnapshot.snapshot_date < today,
        )
        .order_by(FinancialSnapshot.snapshot_date.asc())
        .limit(1)
    )
    ytd_baseline = ytd_row.net_worth if ytd_row is not None else None
    ytd_change = net_worth - ytd_baseline if ytd_baseline is not None else Decimal("0")

    account_ids = [account.id for account in accounts]
    current_transactions = _load_transactions(db, user, start, today, account_ids)
    previous_transactions = _load_transactions(db, user, previous_start, previous_end, account_ids)
    cash_flow = _cash_flow_series(current_transactions, bucket)
    average_income, income_variability = _income_stats(current_transactions)

    account_snapshot_start = db.scalar(
        select(func.min(AccountBalanceSnapshot.snapshot_date)).where(
            AccountBalanceSnapshot.user_id == user.id,
            AccountBalanceSnapshot.currency == currency,
        )
    )
    financial_snapshot_start = db.scalar(
        select(func.min(FinancialSnapshot.snapshot_date)).where(
            FinancialSnapshot.user_id == user.id,
            FinancialSnapshot.currency == currency,
        )
    )
    account_snapshot_days = db.scalar(
        select(func.count(func.distinct(AccountBalanceSnapshot.snapshot_date))).where(
            AccountBalanceSnapshot.user_id == user.id,
            AccountBalanceSnapshot.currency == currency,
        )
    ) or 0

    return {
        "generated_at": datetime.now(ZoneInfo(user.settings.timezone)),
        "currency": currency,
        "period": {
            "range": range_key,
            "label": label,
            "start": start,
            "end": today,
            "previous_start": previous_start,
            "previous_end": previous_end,
            "bucket": bucket,
        },
        "summary": {
            "net_worth": money(net_worth),
            "assets": money(assets),
            "liabilities": money(liabilities),
            "cash_available": money(cash),
            "change_amount": money(change),
            "change_percent": _percent_change(net_worth, baseline),
            "ytd_change_amount": money(ytd_change),
            "ytd_change_percent": _percent_change(net_worth, ytd_baseline),
            "average_monthly_income": average_income,
            "income_variability_percent": income_variability,
        },
        "net_worth_history": history,
        "balance_history": balance_history,
        "composition": _composition(accounts),
        "account_contributions": _account_contributions(db, user, accounts, start, today),
        "cash_flow": cash_flow,
        "spending_categories": _spending_categories(current_transactions, previous_transactions),
        "income_sources": _income_sources(current_transactions, previous_transactions),
        "history": {
            "financial_snapshot_start": financial_snapshot_start,
            "account_snapshot_start": account_snapshot_start,
            "account_snapshot_days": int(account_snapshot_days),
            "account_tracking_active": account_snapshot_start is not None,
        },
    }
