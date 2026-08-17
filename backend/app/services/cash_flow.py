from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ApiError
from app.models import Account, Transaction, User
from app.services.transaction_intelligence import effective_category, effective_kind, effective_merchant
from app.services.views import money

RangeKey = Literal["month", "year", "custom"]


def _previous_month_bounds(start: date) -> tuple[date, date]:
    previous_end = start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    return previous_start, previous_end


def cash_flow_period(
    user: User,
    *,
    range_key: RangeKey,
    month: str | None = None,
    year: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[date, date, date, date, str]:
    local_today = datetime.now(ZoneInfo(user.settings.timezone)).date()

    if range_key == "month":
        if month is None:
            selected_year, selected_month = local_today.year, local_today.month
        else:
            try:
                parsed = datetime.strptime(month, "%Y-%m")
                if parsed.strftime("%Y-%m") != month:
                    raise ValueError
            except ValueError as exc:
                raise ApiError(422, "invalid_month", "Month must use YYYY-MM format") from exc
            selected_year, selected_month = parsed.year, parsed.month
        start = date(selected_year, selected_month, 1)
        end = date(selected_year, selected_month, calendar.monthrange(selected_year, selected_month)[1])
        previous_start, previous_end = _previous_month_bounds(start)
        label = start.strftime("%B %Y")
        return start, end, previous_start, previous_end, label

    if range_key == "year":
        selected_year = year or local_today.year
        if selected_year < 2000 or selected_year > 2100:
            raise ApiError(422, "invalid_year", "Year must be between 2000 and 2100")
        start = date(selected_year, 1, 1)
        end = date(selected_year, 12, 31)
        return start, end, date(selected_year - 1, 1, 1), date(selected_year - 1, 12, 31), str(selected_year)

    if start_date is None or end_date is None:
        raise ApiError(422, "invalid_date_range", "Custom cash flow requires start_date and end_date")
    if start_date > end_date:
        raise ApiError(422, "invalid_date_range", "Start date must not be after end date")
    if (end_date - start_date).days >= 366:
        raise ApiError(422, "invalid_date_range", "Custom cash flow ranges may span at most 366 days")
    duration = end_date - start_date
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - duration
    label = f"{start_date.isoformat()} – {end_date.isoformat()}"
    return start_date, end_date, previous_start, previous_end, label


def _load_transactions(db: Session, user: User, start: date, end: date) -> tuple[list[Transaction], int]:
    account_ids = list(
        db.scalars(
            select(Account.id).where(
                Account.user_id == user.id,
                Account.currency == user.settings.currency,
            )
        ).all()
    )
    if not account_ids:
        return [], 0
    transactions = list(
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
    transfer_count = sum(
        1
        for transaction in transactions
        if effective_kind(transaction) == "transfer" or transaction.excluded_from_spending
    )
    return transactions, transfer_count


def _aggregate(transactions: list[Transaction]) -> dict[str, object]:
    income_sources: dict[str, dict[str, object]] = {}
    categories: dict[str, dict[str, object]] = {}
    income = Decimal("0")
    refunds = Decimal("0")
    spending = Decimal("0")
    included_count = 0

    for transaction in transactions:
        kind = effective_kind(transaction)
        if kind == "transfer" or transaction.excluded_from_spending:
            continue
        included_count += 1
        amount = transaction.amount
        category = effective_category(transaction)

        if kind == "income":
            income += amount
            label = (effective_merchant(transaction) or "Income").strip() or "Income"
            normalized = label.casefold()
            row = income_sources.setdefault(
                normalized,
                {"label": label, "amount": Decimal("0"), "count": 0},
            )
            row["amount"] = Decimal(row["amount"]) + amount
            row["count"] = int(row["count"]) + 1
            continue

        if kind == "refund":
            refunds += amount
            continue

        if kind == "expense":
            expense = -amount
            if expense <= 0:
                continue
            spending += expense
            key = category.stable_key if category else "other"
            row = categories.setdefault(
                key,
                {
                    "label": category.name if category else "Other",
                    "amount": Decimal("0"),
                    "count": 0,
                    "category_id": category.id if category else None,
                },
            )
            row["amount"] = Decimal(row["amount"]) + expense
            row["count"] = int(row["count"]) + 1

    inflow = income + refunds
    net_cash_flow = inflow - spending
    retained_cash = max(net_cash_flow, Decimal("0"))
    shortfall = max(-net_cash_flow, Decimal("0"))
    return {
        "income": income,
        "refunds": refunds,
        "inflow": inflow,
        "spending": spending,
        "net_cash_flow": net_cash_flow,
        "retained_cash": retained_cash,
        "shortfall": shortfall,
        "included_count": included_count,
        "income_sources": income_sources,
        "categories": categories,
    }


def _change_percent(current: Decimal, previous: Decimal) -> str | None:
    if previous <= 0:
        return None
    return money((current - previous) / previous * Decimal("100"))


def _node(
    *,
    node_id: str,
    label: str,
    kind: str,
    amount: Decimal,
    count: int,
    previous: Decimal = Decimal("0"),
    category_id: int | None = None,
    filters: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": node_id,
        "label": label,
        "kind": kind,
        "amount": money(amount),
        "transaction_count": count,
        "previous_amount": money(previous),
        "change_percent": _change_percent(amount, previous),
        "category_id": category_id,
        "filters": filters,
    }


def cash_flow_sankey(
    db: Session,
    user: User,
    *,
    range_key: RangeKey,
    month: str | None = None,
    year: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, object]:
    start, end, previous_start, previous_end, label = cash_flow_period(
        user,
        range_key=range_key,
        month=month,
        year=year,
        start_date=start_date,
        end_date=end_date,
    )
    current_transactions, transfer_count = _load_transactions(db, user, start, end)
    previous_transactions, _ = _load_transactions(db, user, previous_start, previous_end)
    current = _aggregate(current_transactions)
    previous = _aggregate(previous_transactions)

    current_sources = current["income_sources"]
    previous_sources = previous["income_sources"]
    assert isinstance(current_sources, dict)
    assert isinstance(previous_sources, dict)
    current_categories = current["categories"]
    previous_categories = previous["categories"]
    assert isinstance(current_categories, dict)
    assert isinstance(previous_categories, dict)

    nodes: list[dict[str, object]] = []
    links: list[dict[str, object]] = []

    ranked_sources = sorted(
        current_sources.items(),
        key=lambda item: (-Decimal(item[1]["amount"]), str(item[1]["label"])),
    )
    visible_sources = ranked_sources[:7]
    overflow_sources = ranked_sources[7:]
    for normalized, row in visible_sources:
        amount = Decimal(row["amount"])
        previous_row = previous_sources.get(normalized, {})
        previous_amount = Decimal(previous_row.get("amount", 0))
        node_id = f"income:{len(nodes)}"
        filters = {"kind": "income", "search": str(row["label"])}
        nodes.append(
            _node(
                node_id=node_id,
                label=str(row["label"]),
                kind="income_source",
                amount=amount,
                count=int(row["count"]),
                previous=previous_amount,
                filters=filters,
            )
        )
        links.append(
            {
                "id": f"{node_id}->cash-in",
                "source": node_id,
                "target": "cash-in",
                "label": str(row["label"]),
                "kind": "income",
                "amount": money(amount),
                "transaction_count": int(row["count"]),
                "share_percent": None,
                "filters": filters,
            }
        )

    if overflow_sources:
        amount = sum((Decimal(row["amount"]) for _, row in overflow_sources), Decimal("0"))
        count = sum(int(row["count"]) for _, row in overflow_sources)
        nodes.append(
            _node(
                node_id="income:other",
                label="Other income",
                kind="income_source",
                amount=amount,
                count=count,
                filters={"kind": "income"},
            )
        )
        links.append(
            {
                "id": "income:other->cash-in",
                "source": "income:other",
                "target": "cash-in",
                "label": "Other income",
                "kind": "income",
                "amount": money(amount),
                "transaction_count": count,
                "share_percent": None,
                "filters": {"kind": "income"},
            }
        )

    refunds = Decimal(current["refunds"])
    if refunds > 0:
        filters = {"kind": "refund"}
        nodes.append(
            _node(
                node_id="refunds",
                label="Refunds",
                kind="refund",
                amount=refunds,
                count=sum(1 for item in current_transactions if effective_kind(item) == "refund" and not item.excluded_from_spending),
                previous=Decimal(previous["refunds"]),
                filters=filters,
            )
        )
        links.append(
            {
                "id": "refunds->cash-in",
                "source": "refunds",
                "target": "cash-in",
                "label": "Refunds",
                "kind": "refund",
                "amount": money(refunds),
                "transaction_count": sum(1 for item in current_transactions if effective_kind(item) == "refund" and not item.excluded_from_spending),
                "share_percent": None,
                "filters": filters,
            }
        )

    shortfall = Decimal(current["shortfall"])
    if shortfall > 0:
        nodes.append(
            _node(
                node_id="shortfall",
                label="Cash shortfall",
                kind="shortfall",
                amount=shortfall,
                count=0,
                previous=Decimal(previous["shortfall"]),
            )
        )
        links.append(
            {
                "id": "shortfall->cash-in",
                "source": "shortfall",
                "target": "cash-in",
                "label": "Cash shortfall",
                "kind": "shortfall",
                "amount": money(shortfall),
                "transaction_count": 0,
                "share_percent": None,
                "filters": None,
            }
        )

    flow_total = max(Decimal(current["inflow"]), Decimal(current["spending"]))
    nodes.append(
        _node(
            node_id="cash-in",
            label="Available cash",
            kind="hub",
            amount=flow_total,
            count=int(current["included_count"]),
            previous=max(Decimal(previous["inflow"]), Decimal(previous["spending"])),
        )
    )

    ranked_categories = sorted(
        current_categories.items(),
        key=lambda item: (-Decimal(item[1]["amount"]), str(item[1]["label"])),
    )
    special_keys = {"debt_payments", "savings"}
    special_categories = [item for item in ranked_categories if item[0] in special_keys]
    regular_categories = [item for item in ranked_categories if item[0] not in special_keys]
    visible_categories = regular_categories[:7] + special_categories
    visible_categories.sort(key=lambda item: (-Decimal(item[1]["amount"]), str(item[1]["label"])))

    for category_key, row in visible_categories:
        amount = Decimal(row["amount"])
        previous_row = previous_categories.get(category_key, {})
        previous_amount = Decimal(previous_row.get("amount", 0))
        category_id = row.get("category_id")
        node_kind = "debt" if category_key == "debt_payments" else "savings" if category_key == "savings" else "expense"
        node_id = f"category:{category_key}"
        filters = {"kind": "expense", "category_id": category_id} if category_id else {"kind": "expense"}
        nodes.append(
            _node(
                node_id=node_id,
                label=str(row["label"]),
                kind=node_kind,
                amount=amount,
                count=int(row["count"]),
                previous=previous_amount,
                category_id=category_id if isinstance(category_id, int) else None,
                filters=filters,
            )
        )
        links.append(
            {
                "id": f"cash-in->{node_id}",
                "source": "cash-in",
                "target": node_id,
                "label": str(row["label"]),
                "kind": node_kind,
                "amount": money(amount),
                "transaction_count": int(row["count"]),
                "share_percent": money(amount / flow_total * Decimal("100")) if flow_total > 0 else None,
                "filters": filters,
            }
        )

    overflow_categories = regular_categories[7:]
    if overflow_categories:
        overflow_keys = {key for key, _ in overflow_categories}
        amount = sum((Decimal(row["amount"]) for _, row in overflow_categories), Decimal("0"))
        count = sum(int(row["count"]) for _, row in overflow_categories)
        previous_amount = sum(
            (Decimal(previous_categories.get(key, {}).get("amount", 0)) for key in overflow_keys),
            Decimal("0"),
        )
        nodes.append(
            _node(
                node_id="category:other-spending",
                label="Other spending",
                kind="expense",
                amount=amount,
                count=count,
                previous=previous_amount,
            )
        )
        links.append(
            {
                "id": "cash-in->category:other-spending",
                "source": "cash-in",
                "target": "category:other-spending",
                "label": "Other spending",
                "kind": "expense",
                "amount": money(amount),
                "transaction_count": count,
                "share_percent": money(amount / flow_total * Decimal("100")) if flow_total > 0 else None,
                "filters": None,
            }
        )

    retained_cash = Decimal(current["retained_cash"])
    if retained_cash > 0:
        nodes.append(
            _node(
                node_id="retained-cash",
                label="Retained cash",
                kind="savings",
                amount=retained_cash,
                count=0,
                previous=Decimal(previous["retained_cash"]),
            )
        )
        links.append(
            {
                "id": "cash-in->retained-cash",
                "source": "cash-in",
                "target": "retained-cash",
                "label": "Retained cash",
                "kind": "savings",
                "amount": money(retained_cash),
                "transaction_count": 0,
                "share_percent": money(retained_cash / flow_total * Decimal("100")) if flow_total > 0 else None,
                "filters": None,
            }
        )

    income = Decimal(current["income"])
    spending = Decimal(current["spending"])
    net_cash_flow = Decimal(current["net_cash_flow"])
    savings_rate = net_cash_flow / income * Decimal("100") if income > 0 else None
    return {
        "period": {
            "range": range_key,
            "label": label,
            "start": start,
            "end": end,
            "previous_start": previous_start,
            "previous_end": previous_end,
        },
        "currency": user.settings.currency,
        "summary": {
            "income": money(income),
            "refunds": money(refunds),
            "inflow": money(Decimal(current["inflow"])),
            "spending": money(spending),
            "net_cash_flow": money(net_cash_flow),
            "savings_rate": money(savings_rate),
            "transaction_count": int(current["included_count"]),
            "excluded_transfer_count": transfer_count,
        },
        "nodes": nodes,
        "links": links,
    }
