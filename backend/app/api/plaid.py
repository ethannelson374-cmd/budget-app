from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.schemas.api import (
    OkView,
    PlaidConnectionsView,
    PlaidExchangeRequest,
    PlaidLinkTokenView,
)
from app.services.auth import Principal, add_audit_event
from app.services.plaid import create_link_token, disconnect, exchange_and_import, list_connections

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
