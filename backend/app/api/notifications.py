from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request, require_csrf, require_principal
from app.core.config import Settings
from app.schemas.api import (
    NotificationCountView,
    NotificationListView,
    NotificationPatch,
    NotificationPreferencesPatch,
    NotificationPreferencesView,
    NotificationView,
    OkView,
)
from app.services.auth import Principal, add_audit_event
from app.services.notifications import (
    get_preferences,
    list_notifications,
    mark_all_read,
    mark_notification,
    notification_view,
    preferences_view,
    unread_count,
    update_preferences,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListView)
def notifications_list(
    status: Annotated[Literal["all", "unread"], Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return list_notifications(db, principal.user, status=status, limit=limit)


@router.get("/unread-count", response_model=NotificationCountView)
def notifications_unread_count(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return {"unread_count": unread_count(db, principal.user)}


@router.get("/preferences", response_model=NotificationPreferencesView)
def notification_preferences(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    row = get_preferences(db, principal.user)
    return preferences_view(row, settings)


@router.patch("/preferences", response_model=NotificationPreferencesView)
def notification_preferences_update(
    payload: NotificationPreferencesPatch,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    result = update_preferences(db, principal.user, payload.model_dump(exclude_unset=True), settings)
    add_audit_event(
        db,
        settings,
        action="notifications.preferences_update",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail="preferences",
    )
    db.commit()
    return result


@router.patch("/{notification_id}", response_model=NotificationView)
def notification_update(
    notification_id: int,
    payload: NotificationPatch,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    row = mark_notification(
        db,
        principal.user,
        notification_id,
        read=payload.read if "read" in payload.model_fields_set else None,
        dismissed=payload.dismissed if "dismissed" in payload.model_fields_set else None,
    )
    add_audit_event(
        db,
        settings,
        action="notification.update",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"notification:{notification_id}",
    )
    db.commit()
    return notification_view(row)


@router.post("/read-all", response_model=OkView)
def notifications_read_all(
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    count = mark_all_read(db, principal.user)
    add_audit_event(
        db,
        settings,
        action="notifications.read_all",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
        detail=f"count={count}",
    )
    db.commit()
    return {"ok": True}
