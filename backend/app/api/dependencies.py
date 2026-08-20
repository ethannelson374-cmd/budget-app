from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import cast
from urllib.parse import urlsplit

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import cookie_name, csrf_digest
from app.models import User
from app.services.auth import Principal, load_principal
from app.services.family import budget_user


def get_settings_from_request(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.database.session()


def get_optional_principal(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_request),
) -> Principal | None:
    token = request.cookies.get(cookie_name(settings))
    if not token:
        return None
    return load_principal(db, settings, token)


def require_principal(
    principal: Principal | None = Depends(get_optional_principal),
) -> Principal:
    if principal is None:
        raise ApiError(401, "authentication_required", "Authentication is required")
    return principal


def _origin_tuple(value: str) -> tuple[str, str] | None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed.scheme.lower(), parsed.netloc.lower()


def require_csrf(
    request: Request,
    principal: Principal = Depends(require_principal),
    settings: Settings = Depends(get_settings_from_request),
) -> Principal:
    supplied = request.headers.get("X-CSRF-Token", "")
    expected_digest = principal.session.csrf_digest
    if not supplied or not hmac.compare_digest(csrf_digest(settings, supplied), expected_digest):
        raise ApiError(403, "csrf_failed", "The request could not be verified")

    expected_origin = (request.url.scheme.lower(), request.url.netloc.lower())
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    candidate = _origin_tuple(origin) if origin else _origin_tuple(referer) if referer else None
    if candidate is None or not hmac.compare_digest(
        f"{candidate[0]}://{candidate[1]}",
        f"{expected_origin[0]}://{expected_origin[1]}",
    ):
        raise ApiError(403, "origin_failed", "The request origin could not be verified")
    return principal


def require_budget_user(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the financial owner for the current shared Budget membership."""
    return budget_user(db, principal.user)
