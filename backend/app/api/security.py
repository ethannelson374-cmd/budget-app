from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_db,
    get_optional_principal,
    get_settings_from_request,
    require_csrf,
    require_principal,
)
from app.api.setup import _client_ip, _set_session_cookie
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import cookie_name, utc_now
from app.integrations.google_oidc import GoogleOIDCError, exchange_code, validate_id_token
from app.models import InstallationState, PlaidItem, User
from app.schemas.api import (
    AccountDeleteRequest,
    AdminUserListView,
    AuthView,
    InvitationAcceptRequest,
    InvitationCreateRequest,
    InvitationListView,
    InvitationPublicView,
    InvitationView,
    OkView,
    PasswordForgotRequest,
    PasswordResetDeliveryView,
    PasswordResetRequest,
    PasswordResetStatusView,
    SecurityStatusView,
    SessionListView,
    TotpConfirmRequest,
    TotpConfirmView,
    TotpSetupView,
    TwoFactorLoginRequest,
)
from app.services.auth import Principal, add_audit_event, issue_session
from app.services.identity import (
    accept_password_invitation,
    admin_password_reset,
    admin_users,
    begin_google_flow,
    begin_totp_setup,
    can_delete_admin,
    complete_google_flow,
    confirm_totp,
    consume_two_factor_challenge,
    create_invitation,
    disable_totp,
    invitation_from_token,
    invitation_public_view,
    list_invitations,
    list_sessions,
    oauth_state,
    password_reset_status,
    request_password_reset,
    reset_password,
    revoke_invitation,
    revoke_named_session,
    revoke_other_sessions,
    security_status,
    unlink_google,
    verify_account_delete_password,
)
from app.services.plaid import disconnect
from app.services.setup import INSTALLATION_ROW_ID
from app.services.views import user_view

router = APIRouter(prefix="/auth", tags=["identity and security"])


def _base_url(settings: Settings, request: Request) -> str:
    return settings.public_app_url or f"{request.url.scheme}://{request.url.netloc}"


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post("/two-factor/login", response_model=AuthView)
def two_factor_login(
    payload: TwoFactorLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    try:
        user = consume_two_factor_challenge(
            db,
            settings,
            token=payload.challenge_token.get_secret_value(),
            code=payload.code,
        )
    except ApiError:
        db.commit()
        raise
    user.last_login_at = utc_now()
    token, csrf_token, _ = issue_session(
        db,
        settings,
        user,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    add_audit_event(
        db,
        settings,
        action="auth.login.two_factor",
        outcome="success",
        request_id=_request_id(request),
        user_id=user.id,
        detail="challenge_completed",
    )
    db.commit()
    _set_session_cookie(response, settings, token)
    return {"user": user_view(user), "csrf_token": csrf_token}


@router.get("/security", response_model=SecurityStatusView)
def get_security_status(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    return security_status(db, settings, principal.user)


@router.get("/sessions", response_model=SessionListView)
def get_sessions(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return {"sessions": list_sessions(db, principal.user, principal.session.id)}


@router.delete("/sessions/{session_id}", response_model=OkView)
def delete_session(
    session_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    revoke_named_session(db, principal.user, session_id, principal.session.id)
    add_audit_event(
        db,
        settings,
        action="auth.session.revoke",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id,
        detail=f"session:{session_id}",
    )
    db.commit()
    return {"ok": True}


@router.post("/sessions/revoke-others", response_model=OkView)
def revoke_others(
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    count = revoke_other_sessions(db, principal.user, principal.session.id)
    add_audit_event(
        db,
        settings,
        action="auth.session.revoke_others",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id,
        detail=f"revoked:{count}",
    )
    db.commit()
    return {"ok": True}


@router.post("/totp/setup", response_model=TotpSetupView)
def setup_totp(
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, str]:
    result = begin_totp_setup(db, settings, principal.user)
    add_audit_event(
        db,
        settings,
        action="auth.totp.setup",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id,
        detail="pending",
    )
    db.commit()
    return result


@router.post("/totp/confirm", response_model=TotpConfirmView)
def enable_totp(
    payload: TotpConfirmRequest,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    codes = confirm_totp(db, settings, principal.user, payload.code)
    add_audit_event(
        db,
        settings,
        action="auth.totp.enable",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id,
    )
    db.commit()
    return {"recovery_codes": codes}


@router.delete("/totp", response_model=OkView)
def remove_totp(
    payload: TotpConfirmRequest,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    disable_totp(db, settings, principal.user, payload.code)
    add_audit_event(
        db,
        settings,
        action="auth.totp.disable",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id,
    )
    db.commit()
    return {"ok": True}


@router.get("/invitations/{token}", response_model=InvitationPublicView)
def invitation_details(
    token: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    return invitation_public_view(db, settings, token)


@router.post("/invitations/accept", response_model=AuthView)
def accept_invitation(
    payload: InvitationAcceptRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    user = accept_password_invitation(
        db,
        settings,
        token=payload.token.get_secret_value(),
        username=payload.username,
        password=payload.password,
    )
    token, csrf_token, _ = issue_session(
        db,
        settings,
        user,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    add_audit_event(
        db,
        settings,
        action="auth.invitation.accept",
        outcome="success",
        request_id=_request_id(request),
        user_id=user.id,
    )
    db.commit()
    _set_session_cookie(response, settings, token)
    return {"user": user_view(user), "csrf_token": csrf_token}


@router.get("/admin/invitations", response_model=InvitationListView)
def admin_invitations(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return {"invitations": list_invitations(db, principal.user)}


@router.post("/admin/invitations", response_model=InvitationView, status_code=201)
def admin_create_invitation(
    payload: InvitationCreateRequest,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    result = create_invitation(
        db,
        settings,
        principal.user,
        email=str(payload.email),
        base_url=_base_url(settings, request),
    )
    add_audit_event(
        db,
        settings,
        action="auth.invitation.create",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id,
        detail=f"invitation:{result['id']};delivery:{result['delivery']}",
    )
    db.commit()
    return result


@router.delete("/admin/invitations/{invitation_id}", response_model=OkView)
def admin_revoke_invitation(
    invitation_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    revoke_invitation(db, principal.user, invitation_id)
    add_audit_event(
        db,
        settings,
        action="auth.invitation.revoke",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id,
        detail=f"invitation:{invitation_id}",
    )
    db.commit()
    return {"ok": True}


@router.get("/admin/users", response_model=AdminUserListView)
def get_admin_users(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return {"users": admin_users(db, principal.user)}


@router.post("/admin/users/{user_id}/password-reset", response_model=PasswordResetDeliveryView)
def admin_reset_user_password(
    user_id: int,
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    result = admin_password_reset(
        db,
        settings,
        principal.user,
        user_id=user_id,
        base_url=_base_url(settings, request),
    )
    add_audit_event(
        db,
        settings,
        action="auth.password_reset.admin",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id,
        detail=f"target:{user_id};delivery:{result['delivery']}",
    )
    db.commit()
    return result


@router.post("/password/forgot", response_model=OkView)
def forgot_password(
    payload: PasswordForgotRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    delivered = request_password_reset(
        db,
        settings,
        identity=payload.identity,
        base_url=_base_url(settings, request),
    )
    add_audit_event(
        db,
        settings,
        action="auth.password_reset.request",
        outcome="success",
        request_id=_request_id(request),
        identity=payload.identity,
        detail="delivery_attempted" if delivered else "generic_response",
    )
    db.commit()
    # Deliberately non-enumerating regardless of account existence or delivery state.
    return {"ok": True}


@router.get("/password/reset", response_model=PasswordResetStatusView)
def get_password_reset_status(
    token: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, object]:
    return password_reset_status(db, settings, token)


@router.post("/password/reset", response_model=OkView)
def post_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    user = reset_password(
        db,
        settings,
        token=payload.token.get_secret_value(),
        password=payload.password,
    )
    add_audit_event(
        db,
        settings,
        action="auth.password_reset.complete",
        outcome="success",
        request_id=_request_id(request),
        user_id=user.id,
    )
    db.commit()
    return {"ok": True}


@router.get("/google/start")
def google_start(
    request: Request,
    invite: str | None = Query(default=None, max_length=256),
    return_to: str | None = Query(default=None, max_length=500),
    principal: Principal | None = Depends(get_optional_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> RedirectResponse:
    url = begin_google_flow(
        db,
        settings,
        purpose="login",
        user=None,
        invitation_token=invite,
        return_to=return_to,
    )
    add_audit_event(
        db,
        settings,
        action="auth.google.start",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id if principal else None,
        detail="invite" if invite else "login",
    )
    db.commit()
    return RedirectResponse(url=url, status_code=302)


@router.get("/google/link/start")
def google_link_start(
    request: Request,
    return_to: str | None = Query(default="/settings", max_length=500),
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> RedirectResponse:
    url = begin_google_flow(
        db,
        settings,
        purpose="link",
        user=principal.user,
        invitation_token=None,
        return_to=return_to,
    )
    add_audit_event(
        db,
        settings,
        action="auth.google.link_start",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id,
    )
    db.commit()
    return RedirectResponse(url=url, status_code=302)


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str | None = Query(default=None, max_length=4096),
    state: str | None = Query(default=None, max_length=256),
    error: str | None = Query(default=None, max_length=128),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> RedirectResponse:
    if error or not code or not state:
        return RedirectResponse(url=f"/login?auth_error={quote(error or 'google_cancelled')}", status_code=302)
    state_row = None
    try:
        state_row = oauth_state(db, settings, state)
        id_token = exchange_code(settings, code)
        identity = validate_id_token(settings, id_token)
        user, return_to = complete_google_flow(db, settings, state_row=state_row, identity=identity)
        if state_row.purpose == "link":
            add_audit_event(
                db,
                settings,
                action="auth.google.link",
                outcome="success",
                request_id=_request_id(request),
                user_id=user.id,
            )
            db.commit()
            return RedirectResponse(url=f"{return_to}?google=linked", status_code=302)

        user.last_login_at = utc_now()
        token, _, _ = issue_session(
            db,
            settings,
            user,
            client_ip=_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
        )
        add_audit_event(
            db,
            settings,
            action="auth.google.login",
            outcome="success",
            request_id=_request_id(request),
            user_id=user.id,
        )
        db.commit()
        response = RedirectResponse(
            url=f"/auth/google/complete?next={quote(return_to, safe='/')}", status_code=302
        )
        _set_session_cookie(response, settings, token)
        return response
    except (ApiError, GoogleOIDCError) as exc:
        db.rollback()
        code_value = exc.code if isinstance(exc, ApiError) else "google_provider_error"
        destination = "/settings" if state_row is not None and state_row.purpose == "link" else "/login"
        return RedirectResponse(url=f"{destination}?auth_error={quote(code_value)}", status_code=302)


@router.delete("/google", response_model=OkView)
def disconnect_google(
    request: Request,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    unlink_google(db, principal.user)
    add_audit_event(
        db,
        settings,
        action="auth.google.unlink",
        outcome="success",
        request_id=_request_id(request),
        user_id=principal.user.id,
    )
    db.commit()
    return {"ok": True}


@router.delete("/account", response_model=OkView)
def delete_account(
    payload: AccountDeleteRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> dict[str, bool]:
    user = principal.user
    verify_account_delete_password(user, payload.password)
    can_delete_admin(db, user)

    if settings.plaid_configured:
        item_ids = list(db.scalars(select(PlaidItem.id).where(PlaidItem.user_id == user.id)).all())
        for item_id in item_ids:
            disconnect(db, settings, user, item_id)

    remaining_users = int(db.scalar(select(func.count(User.id)).where(User.id != user.id)) or 0)
    email = user.email
    add_audit_event(
        db,
        settings,
        action="auth.account.delete",
        outcome="success",
        request_id=_request_id(request),
        identity=email,
        detail="self_service",
    )
    db.delete(user)
    if remaining_users == 0:
        installation = db.get(InstallationState, INSTALLATION_ROW_ID)
        if installation is not None:
            installation.initialized_at = None
    db.commit()
    response.delete_cookie(
        key=cookie_name(settings),
        path="/",
        secure=settings.is_production,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}
