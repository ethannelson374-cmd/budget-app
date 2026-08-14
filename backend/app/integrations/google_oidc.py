from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import jwt
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError

from app.core.config import Settings

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class GoogleOIDCError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    name: str | None
    nonce: str


def authorization_url(
    settings: Settings,
    *,
    state: str,
    nonce: str,
    login_hint: str | None = None,
) -> str:
    if not settings.google_configured or settings.google_client_id is None or settings.google_redirect_uri is None:
        raise GoogleOIDCError("Google sign-in is not configured")
    query = {
        "client_id": settings.google_client_id.get_secret_value(),
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
    }
    if login_hint:
        query["login_hint"] = login_hint
    return AUTHORIZATION_ENDPOINT + "?" + urllib.parse.urlencode(query)


def exchange_code(settings: Settings, code: str) -> str:
    if (
        not settings.google_configured
        or settings.google_client_id is None
        or settings.google_client_secret is None
        or settings.google_redirect_uri is None
    ):
        raise GoogleOIDCError("Google sign-in is not configured")
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": settings.google_client_id.get_secret_value(),
            "client_secret": settings.google_client_secret.get_secret_value(),
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - fixed Google HTTPS endpoint
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GoogleOIDCError("Google token exchange failed") from exc
    token = payload.get("id_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise GoogleOIDCError("Google did not return an ID token")
    return token


def validate_id_token(settings: Settings, id_token: str) -> GoogleIdentity:
    if settings.google_client_id is None:
        raise GoogleOIDCError("Google sign-in is not configured")
    try:
        jwk_client = PyJWKClient(JWKS_ENDPOINT, timeout=10)
        signing_key = jwk_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id.get_secret_value(),
            issuer=ISSUERS,
            options={"require": ["exp", "iat", "sub", "email", "nonce"]},
        )
    except (InvalidTokenError, PyJWKClientError, OSError) as exc:
        raise GoogleOIDCError("Google ID token validation failed") from exc

    nonce = claims.get("nonce")
    subject = claims.get("sub")
    email = claims.get("email")
    verified = claims.get("email_verified")
    name = claims.get("name")
    if not isinstance(nonce, str) or not nonce:
        raise GoogleOIDCError("Google sign-in nonce was missing")
    if not isinstance(subject, str) or not subject or not isinstance(email, str) or not email:
        raise GoogleOIDCError("Google identity was incomplete")
    if verified not in (True, "true"):
        raise GoogleOIDCError("Google email address is not verified")
    return GoogleIdentity(
        subject=subject,
        email=email,
        email_verified=True,
        name=name if isinstance(name, str) and name.strip() else None,
        nonce=nonce,
    )
