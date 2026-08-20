from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ApiError
from app.models import Account, Category, RecurringStream, Transaction, TransactionRule, User

CADENCES: tuple[tuple[str, int, int, int], ...] = (
    ("weekly", 5, 10, 7),
    ("biweekly", 11, 18, 14),
    ("monthly", 24, 38, 30),
    ("quarterly", 75, 105, 91),
    ("annual", 330, 400, 365),
)

SUBSCRIPTION_MERCHANT_HINTS = (
    "netflix", "spotify", "hulu", "disney", "paramount", "peacock", "youtube",
    "apple.com/bill", "icloud", "google one", "adobe", "microsoft", "xbox",
    "playstation", "dropbox", "canva", "notion", "github", "discord", "openai",
    "chatgpt", "anthropic", "max.com", "audible", "prime membership",
)


def normalize_merchant(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+(?:#|STORE\s*)?\d{2,}\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:[A-Z]{2}|\d{5})(?:\s|$).*$", "", text)
    return text.strip(" -_*/")[:160]


def effective_merchant(transaction: Transaction) -> str | None:
    return transaction.display_merchant or transaction.merchant or transaction.description


def effective_kind(transaction: Transaction) -> str:
    return transaction.user_kind_override or transaction.kind


def effective_category(transaction: Transaction) -> Category | None:
    return transaction.user_category_override or transaction.category


def _matches(rule: TransactionRule, transaction: Transaction) -> bool:
    needle = rule.pattern.casefold()
    merchant = (transaction.merchant or "").casefold()
    description = (transaction.original_description or transaction.description or "").casefold()
    if rule.match_field == "merchant":
        return needle in merchant
    if rule.match_field == "description":
        return needle in description
    return needle in merchant or needle in description


def apply_rules_to_transaction(
    db: Session, user: User, transaction: Transaction, *, allow_replace_rule: bool = True
) -> int | None:
    # Explicit user overrides win over automation. Rule-generated overrides can be refreshed.
    if transaction.applied_rule_id is None and (
        transaction.user_category_override_id is not None
        or transaction.user_kind_override is not None
        or transaction.display_merchant is not None
        or transaction.excluded_from_spending
    ):
        return None
    if not allow_replace_rule and transaction.applied_rule_id is not None:
        return transaction.applied_rule_id

    rules = db.scalars(
        select(TransactionRule)
        .where(TransactionRule.user_id == user.id, TransactionRule.enabled.is_(True))
        .order_by(TransactionRule.priority.asc(), TransactionRule.id.asc())
    ).all()
    for rule in rules:
        if not _matches(rule, transaction):
            continue
        transaction.user_category_override_id = rule.category_id
        transaction.display_merchant = rule.display_merchant
        transaction.user_kind_override = rule.kind_override
        transaction.excluded_from_spending = bool(rule.excluded_from_spending)
        transaction.applied_rule_id = rule.id
        return rule.id

    if transaction.applied_rule_id is not None:
        transaction.user_category_override_id = None
        transaction.display_merchant = None
        transaction.user_kind_override = None
        transaction.excluded_from_spending = False
        transaction.applied_rule_id = None
    return None


def _owned_category(db: Session, user: User, category_id: int | None) -> Category | None:
    if category_id is None:
        return None
    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user.id)
    )
    if category is None:
        raise ApiError(404, "category_not_found", "The category was not found")
    return category


def override_transaction(
    db: Session,
    user: User,
    transaction_id: int,
    *,
    category_id: int | None,
    category_supplied: bool,
    display_merchant: str | None,
    merchant_supplied: bool,
    kind_override: str | None,
    kind_supplied: bool,
    excluded_from_spending: bool | None,
    excluded_supplied: bool,
) -> Transaction:
    transaction = db.scalar(
        select(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.category),
            joinedload(Transaction.user_category_override),
        )
        .where(Transaction.id == transaction_id, Transaction.user_id == user.id)
        .with_for_update()
    )
    if transaction is None:
        raise ApiError(404, "transaction_not_found", "The transaction was not found")
    if category_supplied:
        category = _owned_category(db, user, category_id)
        transaction.user_category_override_id = category.id if category else None
        transaction.user_category_override = category
    if merchant_supplied:
        transaction.display_merchant = display_merchant
    if kind_supplied:
        transaction.user_kind_override = kind_override
    if excluded_supplied and excluded_from_spending is not None:
        transaction.excluded_from_spending = excluded_from_spending
    transaction.applied_rule_id = None
    db.flush()
    return transaction


def create_rule(
    db: Session,
    user: User,
    *,
    name: str,
    match_field: str,
    pattern: str,
    category_id: int | None,
    display_merchant: str | None,
    kind_override: str | None,
    excluded_from_spending: bool | None,
    priority: int,
    enabled: bool,
) -> TransactionRule:
    category = _owned_category(db, user, category_id)
    if category_id is None and not display_merchant and kind_override is None and excluded_from_spending is None:
        raise ApiError(422, "rule_has_no_action", "Choose at least one rule action")
    rule = TransactionRule(
        user_id=user.id,
        name=name,
        match_field=match_field,
        pattern=pattern,
        category_id=category.id if category else None,
        display_merchant=display_merchant,
        kind_override=kind_override,
        excluded_from_spending=excluded_from_spending,
        priority=priority,
        enabled=enabled,
    )
    db.add(rule)
    db.flush()
    reapply_rules(db, user)
    return rule


def list_rules(db: Session, user: User) -> list[TransactionRule]:
    return list(
        db.scalars(
            select(TransactionRule)
            .options(joinedload(TransactionRule.category))
            .where(TransactionRule.user_id == user.id)
            .order_by(TransactionRule.priority, TransactionRule.id)
        ).all()
    )


def delete_rule(db: Session, user: User, rule_id: int) -> None:
    rule = db.scalar(
        select(TransactionRule).where(TransactionRule.id == rule_id, TransactionRule.user_id == user.id)
    )
    if rule is None:
        raise ApiError(404, "transaction_rule_not_found", "The transaction rule was not found")
    affected = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user.id, Transaction.applied_rule_id == rule.id
        )
    ).all()
    for transaction in affected:
        transaction.user_category_override_id = None
        transaction.display_merchant = None
        transaction.user_kind_override = None
        transaction.excluded_from_spending = False
        transaction.applied_rule_id = None
    db.delete(rule)
    db.flush()
    reapply_rules(db, user)


def reapply_rules(db: Session, user: User) -> int:
    transactions = db.scalars(
        select(Transaction).where(Transaction.user_id == user.id, Transaction.source_type == "plaid")
    ).all()
    count = 0
    for transaction in transactions:
        before = transaction.applied_rule_id
        after = apply_rules_to_transaction(db, user, transaction)
        if before != after:
            count += 1
    db.flush()
    return count


def _cadence(intervals: list[int]) -> tuple[str, int] | None:
    if not intervals:
        return None
    mid = int(round(float(median(intervals))))
    for name, minimum, maximum, days in CADENCES:
        if minimum <= mid <= maximum:
            return name, days
    return None


def _subscription_detected(items: list[Transaction], merchant_key: str, kind: str) -> bool:
    if kind != "expense":
        return False
    latest = items[-1]
    category = effective_category(latest)
    if category is not None and category.stable_key == "subscriptions":
        return True
    normalized = merchant_key.casefold()
    return any(hint in normalized for hint in SUBSCRIPTION_MERCHANT_HINTS)


def rebuild_recurring_streams(db: Session, user: User) -> int:
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
                Transaction.pending.is_(False),
                Transaction.excluded_from_spending.is_(False),
            )
            .order_by(Transaction.posted_date, Transaction.id)
        ).all()
    )
    groups: dict[tuple[int, str, str], list[Transaction]] = defaultdict(list)
    for transaction in transactions:
        kind = effective_kind(transaction)
        if kind not in {"income", "expense"}:
            continue
        merchant = normalize_merchant(effective_merchant(transaction))
        if not merchant:
            continue
        groups[(transaction.account_id, merchant.casefold(), kind)].append(transaction)

    existing = {
        (stream.account_id, stream.merchant_key, stream.kind, stream.cadence): (
            stream.subscription_override,
            stream.subscription_status,
        )
        for stream in db.scalars(
            select(RecurringStream).where(RecurringStream.user_id == user.id)
        ).all()
    }
    db.execute(delete(RecurringStream).where(RecurringStream.user_id == user.id))
    created = 0
    for (account_id, merchant_key, kind), items in groups.items():
        if len(items) < 3:
            continue
        dates = [item.posted_date for item in items]
        intervals = [(b - a).days for a, b in zip(dates, dates[1:], strict=False) if (b - a).days > 0]
        cadence = _cadence(intervals)
        if cadence is None:
            continue
        cadence_name, cadence_days = cadence
        amounts = [abs(item.amount) for item in items]
        average = sum(amounts, Decimal("0")) / Decimal(len(amounts))
        if average == 0:
            continue
        last_amount = amounts[-1]
        previous_average = (
            sum(amounts[:-1], Decimal("0")) / Decimal(len(amounts) - 1)
            if len(amounts) > 1
            else average
        )
        change_pct = None
        if previous_average > 0:
            change_pct = (last_amount - previous_average) / previous_average * Decimal("100")
        display_name = normalize_merchant(effective_merchant(items[-1])) or items[-1].description
        subscription_override, subscription_status = existing.get(
            (account_id, merchant_key, kind, cadence_name),
            (None, "active"),
        )
        db.add(
            RecurringStream(
                user_id=user.id,
                account_id=account_id,
                merchant_key=merchant_key[:160],
                display_name=display_name[:160],
                kind=kind,
                cadence=cadence_name,
                average_amount=average,
                last_amount=last_amount,
                last_date=dates[-1],
                next_expected_date=dates[-1] + timedelta(days=cadence_days),
                occurrence_count=len(items),
                price_change_pct=change_pct,
                subscription_detected=_subscription_detected(items, merchant_key, kind),
                subscription_override=subscription_override,
                subscription_status=subscription_status,
                active=True,
            )
        )
        created += 1
    db.flush()
    return created


def list_recurring_streams(db: Session, user: User) -> list[RecurringStream]:
    return list(
        db.scalars(
            select(RecurringStream)
            .options(joinedload(RecurringStream.account))
            .where(RecurringStream.user_id == user.id, RecurringStream.active.is_(True))
            .order_by(RecurringStream.next_expected_date, RecurringStream.display_name)
        ).all()
    )
