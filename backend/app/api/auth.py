from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import (
    get_db,
    get_settings_from_request,
    require_csrf,
    require_principal,
)
from app.api.setup import _client_ip, _set_session_cookie
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import cookie_name, utc_now
from app.models import User
from app.schemas.api import AuthView, LoginRequest, OkView
from app.services.auth import (
    Principal,
    add_audit_event,
    check_user_password,
    clear_login_failures,
    find_user_for_login,
    issue_session,
    login_attempt_guard,
    record_login_failure,
    revoke_session,
    throttle_keys,
    throttled_for,
    update_password,
)
from app.services.views import user_view

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=AuthView)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    with login_attempt_guard():
        now = utc_now()
        keys = throttle_keys(settings, payload.identity, _client_ip(request))
        retry_after = throttled_for(db, keys, now)
        if retry_after:
            add_audit_event(
                db,
                settings,
                action="auth.login",
                outcome="blocked",
                request_id=getattr(request.state, "request_id", None),
                identity=payload.identity,
            )
            db.commit()
            raise ApiError(
                429,
                "login_rate_limited",
                "Too many login attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )

        user = find_user_for_login(db, payload.identity)
        valid, needs_rehash = check_user_password(user, payload.password)
        if not valid or user is None:
            record_login_failure(db, keys, now)
            add_audit_event(
                db,
                settings,
                action="auth.login",
                outcome="failure",
                request_id=getattr(request.state, "request_id", None),
                identity=payload.identity,
            )
            db.commit()
            raise ApiError(
                401,
                "invalid_credentials",
                "The username/email or password is incorrect",
            )

        if needs_rehash:
            update_password(user, payload.password)
        user.last_login_at = now
        clear_login_failures(db, keys)
        token, csrf_token, _ = issue_session(db, settings, user, client_ip=_client_ip(request))
        add_audit_event(
            db,
            settings,
            action="auth.login",
            outcome="success",
            request_id=getattr(request.state, "request_id", None),
            user_id=user.id,
        )
        db.commit()
    _set_session_cookie(response, settings, token)
    return {"user": user_view(user), "csrf_token": csrf_token}


@router.post("/demo-login", response_model=AuthView)
def demo_login(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    if not settings.demo_mode or settings.is_production:
        raise ApiError(404, "not_found", "The requested endpoint was not found")
    user = db.scalar(
        select(User).options(joinedload(User.settings)).where(User.normalized_username == "demo")
    )
    if user is None:
        raise ApiError(503, "demo_unavailable", "Demo data has not been initialized")
    token, csrf_token, _ = issue_session(db, settings, user, client_ip=_client_ip(request))
    add_audit_event(
        db,
        settings,
        action="auth.demo_login",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=user.id,
    )
    db.commit()
    _set_session_cookie(response, settings, token)
    return {"user": user_view(user), "csrf_token": csrf_token}


@router.get("/me", response_model=AuthView)
def me(principal: Principal = Depends(require_principal)) -> dict[str, object]:
    return {"user": user_view(principal.user), "csrf_token": principal.csrf_token}


@router.post("/logout", response_model=OkView)
def logout(
    request: Request,
    response: Response,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    revoke_session(db, principal.session)
    add_audit_event(
        db,
        settings,
        action="auth.logout",
        outcome="success",
        request_id=getattr(request.state, "request_id", None),
        user_id=principal.user.id,
    )
    db.commit()
    response.delete_cookie(
        key=cookie_name(settings),
        path="/",
        secure=settings.is_production,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}
