from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.plaid_webhook import PlaidWebhookVerificationError, verify_plaid_webhook
from app.core.security import as_utc, utc_now
from app.models import PlaidItem
from app.schemas.api import (
    OkView,
    PlaidConnectionsView,
    PlaidExchangeRequest,
    PlaidLinkTokenView,
    PlaidSyncResultView,
)
from app.services.auth import Principal, add_audit_event
from app.services.plaid import (
    create_link_token,
    create_update_link_token,
    disconnect,
    exchange_and_import,
    list_connections,
    refresh_connection,
)
from app.services.plaid_transactions import sync_outcome_view, sync_plaid_item

router = APIRouter(prefix="/plaid", tags=["plaid"])


def _webhook_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return as_utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _matching_item(db: Session, payload: dict[str, Any]) -> PlaidItem | None:
    external_id = payload.get("item_id")
    if not isinstance(external_id, str) or not external_id:
        return None
    item = db.scalar(select(PlaidItem).where(PlaidItem.external_id == external_id))
    if item is None:
        return None
    environment = payload.get("environment")
    if isinstance(environment, str) and environment in {"sandbox", "production"}:
        if item.environment != environment:
            return None
    return item


def _handle_item_webhook(item: PlaidItem, payload: dict[str, Any]) -> None:
    code = payload.get("webhook_code")
    if not isinstance(code, str):
        return
    item.last_webhook_at = utc_now()

    if code == "ERROR":
        error = payload.get("error")
        error_code = error.get("error_code") if isinstance(error, dict) else None
        if isinstance(error_code, str) and error_code:
            item.status = "error"
            item.last_error_code = error_code[:80]
            # Plaid Item errors are user-visible connection-health failures. Update mode
            # is the first repair path; if Plaid refuses update mode, the user can still
            # remove the Item and establish a fresh connection.
            item.update_required = True
            item.update_reason = error_code[:80]
        return

    if code in {"PENDING_DISCONNECT", "PENDING_EXPIRATION"}:
        item.update_required = True
        item.update_reason = code
        expiration = _webhook_datetime(
            payload.get("consent_expiration_time") or payload.get("disconnect_time")
        )
        if expiration is not None:
            item.consent_expiration_at = expiration
        return

    if code == "NEW_ACCOUNTS_AVAILABLE":
        item.update_required = True
        item.update_reason = code
        return

    if code == "LOGIN_REPAIRED":
        item.status = "active"
        item.last_error_code = None
        item.update_required = False
        item.update_reason = None
        item.sync_requested_at = utc_now()
        return

    if code == "USER_PERMISSION_REVOKED":
        item.status = "error"
        item.last_error_code = code
        item.update_required = True
        item.update_reason = code


@router.post("/webhook", response_model=OkView)
async def webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    raw_body = await request.body()
    try:
        verify_plaid_webhook(settings, request.headers.get("Plaid-Verification"), raw_body)
    except PlaidWebhookVerificationError as exc:
        raise ApiError(401, "plaid_webhook_invalid", "The webhook signature is invalid") from exc
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiError(400, "plaid_webhook_invalid_body", "The webhook body is invalid") from exc
    if not isinstance(payload, dict):
        raise ApiError(400, "plaid_webhook_invalid_body", "The webhook body is invalid")

    webhook_type = payload.get("webhook_type")
    webhook_code = payload.get("webhook_code")
    item = _matching_item(db, payload)
    if item is not None:
        if webhook_type == "TRANSACTIONS" and webhook_code == "SYNC_UPDATES_AVAILABLE":
            item.sync_requested_at = utc_now()
            item.last_webhook_at = utc_now()
        elif webhook_type == "ITEM":
            _handle_item_webhook(item, payload)
        db.commit()
    return {"ok": True}


@router.post("/link-token", response_model=PlaidLinkTokenView)
def link_token(
    principal: Principal = Depends(require_csrf),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    return create_link_token(settings, principal.budget_user)


@router.post("/connections/{item_id}/link-token", response_model=PlaidLinkTokenView)
def update_link_token(
    item_id: int,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    return create_update_link_token(db, settings, principal.budget_user, item_id)


@router.post("/exchange", response_model=PlaidConnectionsView)
def exchange(
    payload: PlaidExchangeRequest,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    exchange_and_import(
        db,
        settings,
        principal.budget_user,
        payload.public_token.get_secret_value(),
        institution_external_id=payload.institution_id,
        link_accounts=[account.model_dump() for account in payload.accounts],
    )
    add_audit_event(
        db,
        settings,
        action="plaid.connect",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail="item_connected",
    )
    db.commit()
    return list_connections(db, settings, principal.budget_user)


@router.get("/connections", response_model=PlaidConnectionsView)
def connections(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    return list_connections(db, settings, principal.budget_user)


@router.post("/connections/{item_id}/refresh", response_model=PlaidConnectionsView)
def refresh_updated_connection(
    item_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    try:
        refresh_connection(db, settings, principal.budget_user, item_id)
    except ApiError:
        # refresh_connection records provider-reported Item health before raising.
        # Commit that state so the Accounts screen can immediately offer repair UI.
        db.commit()
        raise
    add_audit_event(
        db,
        settings,
        action="plaid.update_mode",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"item:{item_id}",
    )
    db.commit()
    return list_connections(db, settings, principal.budget_user)


@router.post("/connections/{item_id}/sync", response_model=PlaidSyncResultView)
def sync_connection(
    item_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    try:
        outcome = sync_plaid_item(db, settings, principal.budget_user, item_id)
    except ApiError:
        # sync_plaid_item applies no transaction changes until all Plaid pages are collected.
        # Commit provider error state when present, then preserve the API error.
        db.commit()
        raise
    add_audit_event(
        db,
        settings,
        action="plaid.transactions_sync",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=(
            f"item:{item_id};added:{outcome.added};modified:{outcome.modified};"
            f"removed:{outcome.removed}"
        ),
    )
    db.commit()
    return sync_outcome_view(outcome)


@router.delete("/connections/{item_id}", response_model=OkView)
def remove_connection(
    item_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    disconnect(db, settings, principal.budget_user, item_id)
    add_audit_event(
        db,
        settings,
        action="plaid.disconnect",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"item:{item_id}",
    )
    db.commit()
    return {"ok": True}
