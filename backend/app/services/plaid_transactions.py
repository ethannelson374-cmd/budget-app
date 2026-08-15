from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import as_utc, utc_now
from app.core.token_crypto import decrypt_plaid_access_token
from app.integrations.plaid import PlaidAPIError, PlaidClient
from app.models import Account, Category, PlaidItem, Transaction, User
from app.services.transaction_intelligence import apply_rules_to_transaction, rebuild_recurring_streams

MUTATION_DURING_PAGINATION = "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"
ITEM_ERRORS = {"ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN", "ITEM_LOCKED"}
MAX_PAGINATION_RESTARTS = 3


@dataclass(slots=True)
class CollectedUpdates:
    added: list[dict[str, Any]]
    modified: list[dict[str, Any]]
    removed: list[str]
    accounts: dict[str, dict[str, Any]]
    next_cursor: str | None
    update_status: str | None


@dataclass(slots=True)
class SyncOutcome:
    item_id: int
    added: int
    modified: int
    removed: int
    update_status: str | None
    last_synced_at: datetime


def _provider_error(exc: PlaidAPIError) -> ApiError:
    status = 503 if exc.status_code >= 500 else 502
    return ApiError(
        status,
        "plaid_sync_failed",
        "Transactions could not be synchronized. Try again.",
    )


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ApiError(502, "plaid_invalid_response", "Plaid returned incomplete transaction data")
    return value


def _optional_string(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _date(value: Any, *, required: bool) -> date | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ApiError(502, "plaid_invalid_response", "Plaid returned an invalid transaction date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(
            502,
            "plaid_invalid_response",
            "Plaid returned an invalid transaction date",
        ) from exc


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ApiError(
            502,
            "plaid_invalid_response",
            "Plaid returned an invalid transaction amount",
        ) from exc


def _collect_updates(
    client: PlaidClient, access_token: str, initial_cursor: str | None
) -> CollectedUpdates:
    for _attempt in range(MAX_PAGINATION_RESTARTS):
        cursor = initial_cursor
        added: list[dict[str, Any]] = []
        modified: list[dict[str, Any]] = []
        removed: list[str] = []
        accounts: dict[str, dict[str, Any]] = {}
        update_status: str | None = None
        while True:
            try:
                payload = client.transactions_sync(access_token, cursor=cursor)
            except PlaidAPIError as exc:
                if exc.error_code == MUTATION_DURING_PAGINATION:
                    break
                raise

            for key, target in (("added", added), ("modified", modified)):
                values = payload.get(key)
                if not isinstance(values, list):
                    raise ApiError(
                        502,
                        "plaid_invalid_response",
                        "Plaid returned incomplete transaction updates",
                    )
                target.extend(item for item in values if isinstance(item, dict))

            removed_values = payload.get("removed")
            if not isinstance(removed_values, list):
                raise ApiError(
                    502,
                    "plaid_invalid_response",
                    "Plaid returned incomplete transaction updates",
                )
            for removed_item in removed_values:
                if not isinstance(removed_item, dict):
                    continue
                transaction_id = removed_item.get("transaction_id")
                if isinstance(transaction_id, str) and transaction_id:
                    removed.append(transaction_id)

            account_values = payload.get("accounts")
            if not isinstance(account_values, list):
                raise ApiError(
                    502,
                    "plaid_invalid_response",
                    "Plaid returned incomplete account updates",
                )
            for account in account_values:
                if isinstance(account, dict):
                    account_id = account.get("account_id")
                    if isinstance(account_id, str) and account_id:
                        accounts[account_id] = account

            next_cursor = payload.get("next_cursor")
            if not isinstance(next_cursor, str):
                raise ApiError(
                    502,
                    "plaid_invalid_response",
                    "Plaid did not return a transaction cursor",
                )
            has_more = bool(payload.get("has_more"))
            if has_more and not next_cursor:
                raise ApiError(
                    502,
                    "plaid_invalid_response",
                    "Plaid returned an invalid pagination cursor",
                )
            if next_cursor:
                cursor = next_cursor
            status = payload.get("transactions_update_status")
            if isinstance(status, str):
                update_status = status
            if not has_more:
                return CollectedUpdates(
                    added=added,
                    modified=modified,
                    removed=removed,
                    accounts=accounts,
                    next_cursor=next_cursor or initial_cursor,
                    update_status=update_status,
                )

    raise ApiError(
        503,
        "plaid_sync_retry_later",
        "Transactions changed while synchronizing. Try again shortly.",
    )


def _account_type(value: Any) -> str:
    candidate = str(value or "other").lower()
    return candidate if candidate in {"depository", "credit", "loan", "investment"} else "other"


def _balance(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _apply_account_updates(
    db: Session,
    user: User,
    item: PlaidItem,
    account_payloads: dict[str, dict[str, Any]],
    now: datetime,
) -> dict[str, Account]:
    existing = db.scalars(
        select(Account).where(
            Account.user_id == user.id,
            Account.plaid_item_id == item.id,
            Account.source_type == "plaid",
        )
    ).all()
    by_external = {account.external_id: account for account in existing if account.external_id}

    for external_id, payload in account_payloads.items():
        account = by_external.get(external_id)
        if account is None:
            account_type = _account_type(payload.get("type"))
            account = Account(
                user_id=user.id,
                institution_id=item.institution_id,
                plaid_item_id=item.id,
                external_id=external_id,
                source_type="plaid",
                name=str(payload.get("name") or "Connected account")[:120],
                account_type=account_type,
                current_balance=Decimal("0"),
                currency=user.settings.currency,
            )
            db.add(account)
            db.flush()
            by_external[external_id] = account

        balances = cast(dict[str, Any], payload.get("balances") or {})
        account_type = _account_type(payload.get("type") or account.account_type)
        account.name = str(payload.get("name") or account.name)[:120]
        official_name = payload.get("official_name")
        account.official_name = _optional_string(official_name, 255)
        account.account_type = account_type
        subtype = payload.get("subtype")
        account.account_subtype = (
            _optional_string(str(subtype), 40) if subtype is not None else None
        )
        current = _balance(balances.get("current"))
        if current is not None:
            account.current_balance = (
                -abs(current) if account_type in {"credit", "loan"} else current
            )
        account.available_balance = _balance(balances.get("available"))
        account.credit_limit = _balance(balances.get("limit"))
        currency = balances.get("iso_currency_code")
        if isinstance(currency, str) and len(currency) == 3:
            account.currency = currency.upper()
        mask = payload.get("mask")
        if mask is not None and str(mask):
            account.mask_last4 = str(mask)[-4:]
        account.last_synced_at = now

    db.flush()
    return by_external


def _category_key(primary: str | None, detailed: str | None) -> str:
    primary = primary or ""
    detailed = detailed or ""
    if primary == "INCOME":
        return "income"
    if primary in {"TRANSFER_IN", "TRANSFER_OUT", "LOAN_DISBURSEMENTS"}:
        return "transfers"
    if primary == "LOAN_PAYMENTS":
        return "transfers" if "CREDIT_CARD" in detailed else "debt_payments"
    if primary == "ENTERTAINMENT":
        return "entertainment"
    if primary == "FOOD_AND_DRINK":
        return "groceries" if "GROCER" in detailed else "restaurants"
    if primary == "GENERAL_MERCHANDISE":
        return "shopping"
    if primary == "HOME_IMPROVEMENT":
        return "housing"
    if primary == "MEDICAL":
        return "healthcare"
    if primary == "RENT_AND_UTILITIES":
        return "housing" if "RENT" in detailed else "utilities"
    if primary == "TRANSPORTATION":
        return "gas" if ("GAS" in detailed or "FUEL" in detailed) else "transportation"
    if primary == "TRAVEL":
        return "transportation"
    return "other"


def _kind(primary: str | None, detailed: str | None, amount: Decimal) -> str:
    if primary in {"TRANSFER_IN", "TRANSFER_OUT", "LOAN_DISBURSEMENTS"}:
        return "transfer"
    if primary == "LOAN_PAYMENTS" and detailed and "CREDIT_CARD" in detailed:
        return "transfer"
    if amount > 0:
        return "income" if primary == "INCOME" else "refund"
    return "expense"


def _category_map(db: Session, user: User) -> dict[str, Category]:
    categories = db.scalars(select(Category).where(Category.user_id == user.id)).all()
    return {category.stable_key: category for category in categories}


def _delete_plaid_transaction(db: Session, user: User, external_id: str) -> int:
    transactions = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.source_type == "plaid",
            Transaction.external_id == external_id,
        )
    ).all()
    for transaction in transactions:
        db.delete(transaction)
    return len(transactions)


def _apply_transaction(
    db: Session,
    user: User,
    accounts: dict[str, Account],
    categories: dict[str, Category],
    payload: dict[str, Any],
    now: datetime,
) -> bool:
    external_id = _required_string(payload, "transaction_id")
    account_external_id = _required_string(payload, "account_id")
    account = accounts.get(account_external_id)
    if account is None:
        raise ApiError(
            409,
            "plaid_account_missing",
            "A Plaid transaction referenced an account that is not connected",
        )

    pfc = cast(dict[str, Any], payload.get("personal_finance_category") or {})
    primary = _optional_string(pfc.get("primary"), 64)
    detailed = _optional_string(pfc.get("detailed"), 128)
    confidence = _optional_string(pfc.get("confidence_level"), 24)
    amount = -_decimal(payload.get("amount"))
    category = categories.get(_category_key(primary, detailed)) or categories.get("other")
    pending_external_id = _optional_string(payload.get("pending_transaction_id"), 255)

    if pending_external_id and pending_external_id != external_id:
        _delete_plaid_transaction(db, user, pending_external_id)

    transaction = db.scalar(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.account_id == account.id,
            Transaction.external_id == external_id,
        )
    )
    created = transaction is None
    if transaction is None:
        transaction = Transaction(
            user_id=user.id,
            account_id=account.id,
            external_id=external_id,
            source_type="plaid",
            posted_date=cast(date, _date(payload.get("date"), required=True)),
            description="Bank transaction",
            amount=amount,
            kind=_kind(primary, detailed, amount),
            imported_at=now,
        )
        db.add(transaction)

    transaction.account_id = account.id
    transaction.category_id = category.id if category else None
    transaction.pending_transaction_external_id = pending_external_id
    transaction.posted_date = cast(date, _date(payload.get("date"), required=True))
    transaction.authorized_date = _date(payload.get("authorized_date"), required=False)
    transaction.merchant = _optional_string(payload.get("merchant_name"), 160)
    name = _optional_string(payload.get("name"), 255)
    transaction.description = name or transaction.merchant or "Bank transaction"
    transaction.original_description = _optional_string(payload.get("original_description"), 512)
    transaction.payment_channel = _optional_string(payload.get("payment_channel"), 32)
    transaction.pfc_primary = primary
    transaction.pfc_detailed = detailed
    transaction.pfc_confidence = confidence
    transaction.amount = amount
    transaction.kind = _kind(primary, detailed, amount)
    transaction.source_type = "plaid"
    transaction.pending = bool(payload.get("pending"))
    transaction.account = account
    transaction.category = category
    apply_rules_to_transaction(db, user, transaction)
    return created


def sync_plaid_item(db: Session, settings: Settings, user: User, item_id: int) -> SyncOutcome:
    if not settings.plaid_configured or settings.encryption_key is None:
        raise ApiError(503, "plaid_unavailable", "Bank connections are not configured")

    item = db.scalar(
        select(PlaidItem)
        .options(joinedload(PlaidItem.institution))
        .where(PlaidItem.id == item_id, PlaidItem.user_id == user.id)
        .with_for_update()
    )
    if item is None:
        raise ApiError(404, "plaid_connection_not_found", "The bank connection was not found")
    if item.environment != settings.plaid_env:
        raise ApiError(
            409,
            "plaid_environment_mismatch",
            "This bank connection belongs to a different Plaid environment.",
        )

    access_token = decrypt_plaid_access_token(
        item.access_token_ciphertext,
        item.access_token_nonce,
        settings.encryption_key,
        user_id=user.id,
        item_external_id=item.external_id,
    )
    client = PlaidClient(settings)
    try:
        if settings.plaid_webhook_uri and item.webhook_uri != settings.plaid_webhook_uri:
            client.item_webhook_update(access_token, settings.plaid_webhook_uri)
            item.webhook_uri = settings.plaid_webhook_uri
        updates = _collect_updates(client, access_token, item.transactions_cursor)
    except PlaidAPIError as exc:
        item.transactions_last_error_code = exc.error_code[:80]
        if exc.error_code in ITEM_ERRORS:
            item.status = "error"
            item.last_error_code = exc.error_code[:80]
            item.update_required = True
            item.update_reason = exc.error_code[:80]
        db.flush()
        raise _provider_error(exc) from exc

    now = utc_now()
    with db.begin_nested():
        accounts = _apply_account_updates(db, user, item, updates.accounts, now)
        categories = _category_map(db, user)

        removed_count = 0
        for external_id in updates.removed:
            removed_count += _delete_plaid_transaction(db, user, external_id)

        added_count = 0
        for payload in updates.added:
            if _apply_transaction(db, user, accounts, categories, payload, now):
                added_count += 1

        modified_count = 0
        for payload in updates.modified:
            _apply_transaction(db, user, accounts, categories, payload, now)
            modified_count += 1

        item.transactions_cursor = updates.next_cursor
        item.transactions_update_status = updates.update_status
        item.transactions_last_synced_at = now
        item.transactions_last_error_code = None
        item.status = "active"
        item.last_error_code = None
        if item.update_reason == "ITEM_LOGIN_REQUIRED":
            item.update_required = False
            item.update_reason = None
        item.last_synced_at = now
        item.sync_requested_at = None
        rebuild_recurring_streams(db, user)
        db.flush()
    return SyncOutcome(
        item_id=item.id,
        added=added_count,
        modified=modified_count,
        removed=removed_count,
        update_status=updates.update_status,
        last_synced_at=as_utc(now),
    )


def sync_outcome_view(outcome: SyncOutcome) -> dict[str, object]:
    return {
        "connection_id": outcome.item_id,
        "added": outcome.added,
        "modified": outcome.modified,
        "removed": outcome.removed,
        "update_status": outcome.update_status,
        "last_synced_at": outcome.last_synced_at,
    }


def sync_all_plaid_items(
    db: Session, settings: Settings, *, item_id: int | None = None
) -> dict[str, int]:
    if not settings.plaid_configured:
        raise RuntimeError("Plaid is not configured")
    statement = select(PlaidItem.id, PlaidItem.user_id).where(
        PlaidItem.status == "active",
        PlaidItem.environment == settings.plaid_env,
    )
    if item_id is not None:
        statement = statement.where(PlaidItem.id == item_id)
    else:
        stale_before = utc_now() - timedelta(minutes=15)
        statement = statement.where(
            or_(
                PlaidItem.sync_requested_at.is_not(None),
                PlaidItem.transactions_last_synced_at.is_(None),
                PlaidItem.transactions_last_synced_at < stale_before,
            )
        )
    targets = list(db.execute(statement.order_by(PlaidItem.id)).all())
    succeeded = 0
    failed = 0
    for target_item_id, user_id in targets:
        user = db.scalar(
            select(User).options(joinedload(User.settings)).where(User.id == user_id)
        )
        if user is None:
            continue
        try:
            sync_plaid_item(db, settings, user, target_item_id)
            db.commit()
            succeeded += 1
        except ApiError:
            db.commit()
            failed += 1
    return {"succeeded": succeeded, "failed": failed}
