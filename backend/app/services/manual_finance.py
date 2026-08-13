from __future__ import annotations

from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ApiError
from app.core.security import utc_now
from app.models import Account, Category, Transaction, User


ACCOUNT_NON_NULLABLE_FIELDS = {"name", "account_type", "current_balance", "currency"}
TRANSACTION_NON_NULLABLE_FIELDS = {
    "account_id",
    "posted_date",
    "description",
    "amount",
    "kind",
    "pending",
}


def _manual_only(source_type: str, resource: str) -> None:
    if source_type != "manual":
        raise ApiError(
            409,
            f"{resource}_managed_externally",
            f"This {resource.replace('_', ' ')} is managed by a connected provider",
        )


def owned_account(db: Session, user: User, account_id: int) -> Account:
    account = db.scalar(
        select(Account)
        .options(joinedload(Account.institution))
        .where(Account.id == account_id, Account.user_id == user.id)
    )
    if account is None:
        raise ApiError(404, "account_not_found", "The account was not found")
    return account


def owned_category(db: Session, user: User, category_id: int | None) -> Category | None:
    if category_id is None:
        return None
    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user.id)
    )
    if category is None:
        raise ApiError(404, "category_not_found", "The category was not found")
    return category


def create_manual_account(db: Session, user: User, values: dict[str, object]) -> Account:
    account = Account(
        user_id=user.id,
        institution_id=None,
        external_id=None,
        source_type="manual",
        **values,
    )
    db.add(account)
    db.flush()
    return account


def update_manual_account(
    db: Session,
    user: User,
    account_id: int,
    values: dict[str, object],
) -> Account:
    account = owned_account(db, user, account_id)
    _manual_only(account.source_type, "account")
    for field in ACCOUNT_NON_NULLABLE_FIELDS:
        if field in values and values[field] is None:
            raise ApiError(422, "invalid_account", f"{field} may not be null")
    for field, value in values.items():
        setattr(account, field, value)
    db.flush()
    return account


def delete_manual_account(db: Session, user: User, account_id: int) -> None:
    account = owned_account(db, user, account_id)
    _manual_only(account.source_type, "account")
    db.delete(account)
    db.flush()


def validate_transaction_sign(kind: str, amount: Decimal) -> None:
    if kind in {"income", "refund"} and amount < 0:
        raise ApiError(
            422,
            "invalid_transaction_amount",
            "Income and refund amounts must be zero or positive",
        )
    if kind == "expense" and amount > 0:
        raise ApiError(
            422,
            "invalid_transaction_amount",
            "Expense amounts must be zero or negative",
        )


def create_manual_transaction(
    db: Session,
    user: User,
    values: dict[str, object],
) -> Transaction:
    account_id = cast(int, values["account_id"])
    account = owned_account(db, user, account_id)
    if "category_id" in values:
        owned_category(db, user, cast(int | None, values.get("category_id")))
    validate_transaction_sign(cast(str, values["kind"]), cast(Decimal, values["amount"]))
    transaction = Transaction(
        user_id=user.id,
        external_id=None,
        source_type="manual",
        imported_at=utc_now(),
        **values,
    )
    db.add(transaction)
    db.flush()
    transaction.account = account
    transaction.category = owned_category(db, user, transaction.category_id)
    return transaction


def owned_transaction(db: Session, user: User, transaction_id: int) -> Transaction:
    transaction = db.scalar(
        select(Transaction)
        .options(joinedload(Transaction.account), joinedload(Transaction.category))
        .where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    if transaction is None:
        raise ApiError(404, "transaction_not_found", "The transaction was not found")
    return transaction


def update_manual_transaction(
    db: Session,
    user: User,
    transaction_id: int,
    values: dict[str, object],
) -> Transaction:
    transaction = owned_transaction(db, user, transaction_id)
    _manual_only(transaction.source_type, "transaction")
    for field in TRANSACTION_NON_NULLABLE_FIELDS:
        if field in values and values[field] is None:
            raise ApiError(422, "invalid_transaction", f"{field} may not be null")

    next_account = transaction.account
    if "account_id" in values:
        next_account = owned_account(db, user, cast(int, values["account_id"]))
    next_category = transaction.category
    if "category_id" in values:
        next_category = owned_category(db, user, cast(int | None, values.get("category_id")))

    next_kind = cast(str, values.get("kind", transaction.kind))
    next_amount = cast(Decimal, values.get("amount", transaction.amount))
    validate_transaction_sign(next_kind, next_amount)

    for field, value in values.items():
        setattr(transaction, field, value)
    db.flush()
    transaction.account = next_account
    transaction.category = next_category
    return transaction


def delete_manual_transaction(db: Session, user: User, transaction_id: int) -> None:
    transaction = owned_transaction(db, user, transaction_id)
    _manual_only(transaction.source_type, "transaction")
    db.delete(transaction)
    db.flush()
