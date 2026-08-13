from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import as_utc, utc_now
from app.core.token_crypto import decrypt_plaid_access_token, encrypt_plaid_access_token
from app.integrations.plaid import PlaidAPIError, PlaidClient
from app.models import Account, FinancialInstitution, PlaidItem, User
from app.services.views import account_view


def _plaid_failure(exc: PlaidAPIError) -> ApiError:
    status = 503 if exc.status_code >= 500 else 502
    return ApiError(
        status,
        "plaid_request_failed",
        "The bank connection provider could not complete the request. Try again.",
    )


def require_plaid(settings: Settings) -> None:
    if not settings.plaid_configured or settings.plaid_redirect_uri is None:
        raise ApiError(503, "plaid_unavailable", "Bank connections are not configured")
    if settings.encryption_key is None:
        raise ApiError(503, "plaid_unavailable", "Bank connections are not configured")


def create_link_token(settings: Settings, user: User) -> dict[str, object]:
    require_plaid(settings)
    assert settings.plaid_redirect_uri is not None
    try:
        result = PlaidClient(settings).create_link_token(
            client_user_id=f"budget-user-{user.id}",
            redirect_uri=settings.plaid_redirect_uri,
            products=settings.plaid_product_list,
            country_codes=settings.plaid_country_code_list,
        )
    except PlaidAPIError as exc:
        raise _plaid_failure(exc) from exc
    token = result.get("link_token")
    if not isinstance(token, str) or not token:
        raise ApiError(502, "plaid_invalid_response", "The bank connection could not be started")
    return {"link_token": token, "environment": settings.plaid_env}


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _account_type(value: Any) -> str:
    candidate = str(value or "other").lower()
    return candidate if candidate in {"depository", "credit", "loan", "investment"} else "other"


def _signed_current(account_type: str, value: Any) -> Decimal:
    balance = _decimal(value) or Decimal("0")
    return -abs(balance) if account_type in {"credit", "loan"} else balance


def _currency(account: dict[str, Any], fallback: str) -> str:
    balances = cast(dict[str, Any], account.get("balances") or {})
    iso = balances.get("iso_currency_code")
    if isinstance(iso, str) and len(iso) == 3:
        return iso.upper()
    return fallback


def _institution(
    db: Session,
    user: User,
    client: PlaidClient,
    settings: Settings,
    accounts_payload: dict[str, Any],
) -> FinancialInstitution:
    item = cast(dict[str, Any], accounts_payload.get("item") or {})
    external_id = item.get("institution_id")
    if not isinstance(external_id, str) or not external_id:
        raise ApiError(502, "plaid_invalid_response", "The institution could not be identified")

    institution = db.scalar(
        select(FinancialInstitution).where(
            FinancialInstitution.user_id == user.id,
            FinancialInstitution.external_id == external_id,
        )
    )
    metadata: dict[str, Any] = {}
    try:
        metadata_response = client.institution_get(external_id, settings.plaid_country_code_list)
        metadata = cast(dict[str, Any], metadata_response.get("institution") or {})
    except PlaidAPIError:
        # Connection succeeds even when optional institution cosmetics are unavailable.
        metadata = {}

    name = metadata.get("name") or item.get("institution_name") or "Connected institution"
    if institution is None:
        institution = FinancialInstitution(
            user_id=user.id,
            external_id=external_id,
            name=str(name)[:160],
        )
        db.add(institution)
        db.flush()
    else:
        institution.name = str(name)[:160]

    logo = metadata.get("logo")
    primary_color = metadata.get("primary_color")
    url = metadata.get("url")
    institution.logo_base64 = str(logo) if isinstance(logo, str) and logo else None
    institution.primary_color = (
        str(primary_color)[:16] if isinstance(primary_color, str) and primary_color else None
    )
    institution.url = str(url)[:512] if isinstance(url, str) and url else None
    return institution


def _upsert_accounts(
    db: Session,
    user: User,
    plaid_item: PlaidItem,
    institution: FinancialInstitution,
    accounts_payload: list[dict[str, Any]],
) -> list[Account]:
    now = utc_now()
    imported: list[Account] = []
    seen_ids: set[str] = set()
    for payload in accounts_payload:
        external_id = payload.get("account_id")
        if not isinstance(external_id, str) or not external_id:
            continue
        seen_ids.add(external_id)
        account = db.scalar(
            select(Account).where(
                Account.user_id == user.id,
                Account.external_id == external_id,
            )
        )
        account_type = _account_type(payload.get("type"))
        balances = cast(dict[str, Any], payload.get("balances") or {})
        if account is None:
            account = Account(
                user_id=user.id,
                institution_id=institution.id,
                plaid_item_id=plaid_item.id,
                external_id=external_id,
                source_type="plaid",
                name=str(payload.get("name") or "Connected account")[:120],
                account_type=account_type,
                current_balance=Decimal("0"),
                currency=user.settings.currency,
            )
            db.add(account)
        elif account.source_type != "plaid":
            raise ApiError(409, "account_conflict", "A connected account conflicts with local data")

        account.institution_id = institution.id
        account.plaid_item_id = plaid_item.id
        account.name = str(payload.get("name") or "Connected account")[:120]
        official_name = payload.get("official_name")
        account.official_name = (
            str(official_name)[:255] if isinstance(official_name, str) and official_name else None
        )
        account.account_type = account_type
        subtype = payload.get("subtype")
        account.account_subtype = str(subtype)[:40] if subtype is not None else None
        account.current_balance = _signed_current(account_type, balances.get("current"))
        account.available_balance = _decimal(balances.get("available"))
        account.credit_limit = _decimal(balances.get("limit"))
        account.currency = _currency(payload, user.settings.currency)
        mask = payload.get("mask")
        account.mask_last4 = str(mask)[-4:] if mask is not None and str(mask) else None
        account.last_synced_at = now
        imported.append(account)

    # /accounts/get returns active accounts shared for the Item. Remove a previously imported
    # account from this Item if Plaid no longer reports it, while leaving manual data untouched.
    existing = db.scalars(
        select(Account).where(
            Account.user_id == user.id,
            Account.plaid_item_id == plaid_item.id,
            Account.source_type == "plaid",
        )
    ).all()
    for account in existing:
        if account.external_id and account.external_id not in seen_ids:
            db.delete(account)
    db.flush()
    return imported


def _reject_duplicate_item(
    db: Session,
    user: User,
    institution_external_id: str | None,
    link_accounts: list[dict[str, object]],
) -> None:
    if not institution_external_id or not link_accounts:
        return
    institution = db.scalar(
        select(FinancialInstitution).where(
            FinancialInstitution.user_id == user.id,
            FinancialInstitution.external_id == institution_external_id,
        )
    )
    if institution is None:
        return
    existing = db.scalars(
        select(Account).where(
            Account.user_id == user.id,
            Account.institution_id == institution.id,
            Account.source_type == "plaid",
        )
    ).all()
    fingerprints = {(account.name.casefold(), account.mask_last4) for account in existing}
    for account in link_accounts:
        name = account.get("name")
        if not isinstance(name, str):
            continue
        mask = account.get("mask")
        normalized_mask = str(mask)[-4:] if mask is not None and str(mask) else None
        if (name.casefold(), normalized_mask) in fingerprints:
            raise ApiError(
                409,
                "plaid_duplicate_item",
                "This bank account already appears to be connected",
            )


def exchange_and_import(
    db: Session,
    settings: Settings,
    user: User,
    public_token: str,
    *,
    institution_external_id: str | None = None,
    link_accounts: list[dict[str, object]] | None = None,
) -> PlaidItem:
    require_plaid(settings)
    assert settings.encryption_key is not None
    _reject_duplicate_item(db, user, institution_external_id, link_accounts or [])
    client = PlaidClient(settings)
    try:
        exchange = client.exchange_public_token(public_token)
    except PlaidAPIError as exc:
        raise _plaid_failure(exc) from exc
    access_token = exchange.get("access_token")
    item_external_id = exchange.get("item_id")
    if not isinstance(access_token, str) or not access_token:
        raise ApiError(502, "plaid_invalid_response", "The bank connection could not be completed")
    if not isinstance(item_external_id, str) or not item_external_id:
        raise ApiError(502, "plaid_invalid_response", "The bank connection could not be completed")

    existing_item = db.scalar(
        select(PlaidItem).where(
            PlaidItem.user_id == user.id,
            PlaidItem.external_id == item_external_id,
        )
    )
    if existing_item is not None:
        # Do not call /item/remove here: if an update-style flow ever returns the same
        # Item, removing the new token would also revoke the connection we already own.
        raise ApiError(409, "plaid_item_exists", "This bank connection is already linked")

    try:
        try:
            accounts_payload = client.accounts_get(access_token)
        except PlaidAPIError as exc:
            raise _plaid_failure(exc) from exc

        institution = _institution(db, user, client, settings, accounts_payload)
        ciphertext, nonce = encrypt_plaid_access_token(
            access_token,
            settings.encryption_key,
            user_id=user.id,
            item_external_id=item_external_id,
        )
        plaid_item = PlaidItem(
            user_id=user.id,
            institution_id=institution.id,
            external_id=item_external_id,
            access_token_ciphertext=ciphertext,
            access_token_nonce=nonce,
            status="active",
            last_error_code=None,
            last_synced_at=utc_now(),
        )
        db.add(plaid_item)
        db.flush()

        raw_accounts = accounts_payload.get("accounts")
        if not isinstance(raw_accounts, list):
            raise ApiError(502, "plaid_invalid_response", "The linked accounts could not be read")
        _upsert_accounts(
            db,
            user,
            plaid_item,
            institution,
            [item for item in raw_accounts if isinstance(item, dict)],
        )
        return plaid_item
    except Exception:
        # The public-token exchange creates a live Plaid Item. If any later provider or
        # local persistence step fails, revoke that Item best-effort so an unusable
        # connection is not left active outside Budget. Preserve the original error.
        try:
            client.item_remove(access_token)
        except PlaidAPIError:
            pass
        raise


def connection_view(db: Session, user: User, item: PlaidItem) -> dict[str, object]:
    accounts = db.scalars(
        select(Account)
        .options(joinedload(Account.institution))
        .where(Account.user_id == user.id, Account.plaid_item_id == item.id)
        .order_by(Account.name, Account.id)
    ).all()
    institution = item.institution
    return {
        "id": item.id,
        "status": item.status,
        "last_error_code": item.last_error_code,
        "last_synced_at": as_utc(item.last_synced_at) if item.last_synced_at else None,
        "institution": {
            "id": institution.id if institution else None,
            "name": institution.name if institution else "Connected institution",
            "logo": institution.logo_base64 if institution else None,
            "primary_color": institution.primary_color if institution else None,
            "url": institution.url if institution else None,
        },
        "accounts": [account_view(account) for account in accounts],
    }


def list_connections(db: Session, settings: Settings, user: User) -> dict[str, object]:
    if not settings.plaid_configured:
        return {"configured": False, "environment": settings.plaid_env, "connections": []}
    items = db.scalars(
        select(PlaidItem)
        .options(joinedload(PlaidItem.institution))
        .where(PlaidItem.user_id == user.id)
        .order_by(PlaidItem.id)
    ).all()
    return {
        "configured": True,
        "environment": settings.plaid_env,
        "connections": [connection_view(db, user, item) for item in items],
    }


def owned_plaid_item(db: Session, user: User, item_id: int) -> PlaidItem:
    item = db.scalar(
        select(PlaidItem)
        .options(joinedload(PlaidItem.institution))
        .where(PlaidItem.id == item_id, PlaidItem.user_id == user.id)
    )
    if item is None:
        raise ApiError(404, "plaid_connection_not_found", "The bank connection was not found")
    return item


def disconnect(db: Session, settings: Settings, user: User, item_id: int) -> None:
    require_plaid(settings)
    assert settings.encryption_key is not None
    item = owned_plaid_item(db, user, item_id)
    access_token = decrypt_plaid_access_token(
        item.access_token_ciphertext,
        item.access_token_nonce,
        settings.encryption_key,
        user_id=user.id,
        item_external_id=item.external_id,
    )
    try:
        PlaidClient(settings).item_remove(access_token)
    except PlaidAPIError as exc:
        raise _plaid_failure(exc) from exc
    db.delete(item)
    db.flush()
