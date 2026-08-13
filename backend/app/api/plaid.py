from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.plaid_webhook import PlaidWebhookVerificationError, verify_plaid_webhook
from app.core.security import utc_now
from app.models import PlaidItem
from app.schemas.api import (
    OkView,
    PlaidConnectionsView,
    PlaidExchangeRequest,
    PlaidLinkTokenView,
    PlaidSyncResultView,
)
from app.services.auth import Principal, add_audit_event
from app.services.plaid import create_link_token, disconnect, exchange_and_import, list_connections
from app.services.plaid_transactions import sync_outcome_view, sync_plaid_item

router = APIRouter(prefix="/plaid", tags=["plaid"])


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
    if payload.get("webhook_type") == "TRANSACTIONS" and payload.get("webhook_code") == "SYNC_UPDATES_AVAILABLE":
        external_id = payload.get("item_id")
        if isinstance(external_id, str) and external_id:
            item = db.scalar(select(PlaidItem).where(PlaidItem.external_id == external_id))
            if item is not None:
                item.sync_requested_at = utc_now()
                db.commit()
    return {"ok": True}


@router.post("/link-token", response_model=PlaidLinkTokenView)
def link_token(
    principal: Principal = Depends(require_csrf),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    return create_link_token(settings, principal.user)


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
        principal.user,
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
    return list_connections(db, settings, principal.user)


@router.get("/connections", response_model=PlaidConnectionsView)
def connections(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    return list_connections(db, settings, principal.user)


@router.post("/connections/{item_id}/sync", response_model=PlaidSyncResultView)
def sync_connection(
    item_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    try:
        outcome = sync_plaid_item(db, settings, principal.user, item_id)
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
    disconnect(db, settings, principal.user, item_id)
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
