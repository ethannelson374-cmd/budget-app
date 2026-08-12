from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_settings_from_request
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import cookie_name
from app.schemas.api import AuthView, SetupOptionsView, SetupRequest, SetupStatusView
from app.services.auth import add_audit_event, issue_session
from app.services.catalog import CURRENCIES, DEFAULT_CATEGORIES, PAY_FREQUENCIES
from app.services.setup import create_initial_user, installation_initialized
from app.services.views import user_view

router = APIRouter(prefix="/setup", tags=["setup"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=cookie_name(settings),
        value=token,
        max_age=7 * 24 * 60 * 60,
        path="/",
        secure=settings.is_production,
        httponly=True,
        samesite="lax",
    )


@router.get("/status", response_model=SetupStatusView)
def setup_status(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    initialized = installation_initialized(db)
    return {
        "initialized": initialized,
        "demo_mode": settings.demo_mode,
        "bootstrap_required": not initialized
        and (settings.is_production or settings.bootstrap_token is not None),
    }


@router.get("/options", response_model=SetupOptionsView)
def setup_options() -> dict[str, object]:
    return {
        "currencies": list(CURRENCIES),
        "pay_frequencies": list(PAY_FREQUENCIES),
        "default_categories": [
            {
                "key": item["key"],
                "name": item["name"],
                "group": item["group"],
                "selected_by_default": item["selected_by_default"],
            }
            for item in DEFAULT_CATEGORIES
        ],
    }


@router.post("", response_model=AuthView)
def initial_setup(
    payload: SetupRequest,
    request: Request,
    response: Response,
    bootstrap_token: str | None = Header(default=None, alias="X-Bootstrap-Token"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    if settings.is_production and request.url.scheme != "https":
        raise ApiError(400, "https_required", "Initial setup requires HTTPS")

    try:
        user = create_initial_user(db, settings, payload, bootstrap_token)
    except ApiError as exc:
        # Roll back an atomic setup claim, if one was made, before recording a
        # sanitized attempt. The bootstrap credential and request body are
        # never copied into audit metadata.
        db.rollback()
        add_audit_event(
            db,
            settings,
            action="installation.setup",
            outcome="blocked" if exc.status_code == 403 else "failure",
            request_id=getattr(request.state, "request_id", None),
            detail=exc.code,
        )
        db.commit()
        raise
    token, csrf_token, _ = issue_session(db, settings, user, client_ip=_client_ip(request))
    add_audit_event(
        db,
        settings,
        action="installation.setup",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=user.id,
    )
    db.commit()
    _set_session_cookie(response, settings, token)
    return {"user": user_view(user), "csrf_token": csrf_token}
