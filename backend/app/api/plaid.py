from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.core.errors import ApiError
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
