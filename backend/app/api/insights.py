from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.schemas.api import InsightStatusPatch, InsightsView, InsightView
from app.services.auth import Principal, add_audit_event
from app.services.insights import insight_view, list_insights, refresh_insights, set_insight_status

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("", response_model=InsightsView)
def get_insights(
    status: Annotated[
        Literal["active", "dismissed", "resolved", "all"], Query()
    ] = "active",
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return list_insights(db, principal.budget_user, status=status)


@router.post("/refresh", response_model=InsightsView)
def post_refresh_insights(
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    refresh_insights(db, principal.budget_user)
    db.commit()
    return list_insights(db, principal.budget_user, status="active")


@router.patch("/{insight_id}", response_model=InsightView)
def patch_insight(
    insight_id: int,
    payload: InsightStatusPatch,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    row = set_insight_status(db, principal.budget_user, insight_id, payload.status)
    add_audit_event(
        db,
        settings,
        action="insight.status",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"{insight_id}:{payload.status}",
    )
    db.commit()
    return insight_view(row)
