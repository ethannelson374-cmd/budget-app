from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import jwt

from app.core.config import Settings
from app.integrations.plaid import PlaidAPIError, PlaidClient

_KEY_CACHE: dict[str, jwt.PyJWK] = {}


class PlaidWebhookVerificationError(ValueError):
    pass


def _verification_key(settings: Settings, kid: str) -> jwt.PyJWK:
    cached = _KEY_CACHE.get(kid)
    if cached is not None:
        return cached
    try:
        payload = PlaidClient(settings).webhook_verification_key_get(kid)
    except PlaidAPIError as exc:
        raise PlaidWebhookVerificationError("verification key could not be retrieved") from exc
    key_data = payload.get("key")
    if not isinstance(key_data, dict):
        raise PlaidWebhookVerificationError("verification key response is invalid")
    if (
        key_data.get("alg") != "ES256"
        or key_data.get("crv") != "P-256"
        or key_data.get("kty") != "EC"
        or key_data.get("use") != "sig"
        or key_data.get("kid") != kid
    ):
        raise PlaidWebhookVerificationError("verification key metadata is invalid")
    expired_at = key_data.get("expired_at")
    if isinstance(expired_at, (int, float)) and expired_at <= time.time():
        raise PlaidWebhookVerificationError("verification key is expired")
    try:
        key = jwt.PyJWK.from_dict(key_data, algorithm="ES256")
    except jwt.PyJWKError as exc:
        raise PlaidWebhookVerificationError("verification key is invalid") from exc
    _KEY_CACHE[kid] = key
    return key


def verify_plaid_webhook(
    settings: Settings,
    signed_jwt: str | None,
    raw_body: bytes,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    if not settings.plaid_configured:
        raise PlaidWebhookVerificationError("Plaid is not configured")
    if not signed_jwt:
        raise PlaidWebhookVerificationError("Plaid-Verification header is missing")
    try:
        header = jwt.get_unverified_header(signed_jwt)
    except jwt.PyJWTError as exc:
        raise PlaidWebhookVerificationError("verification token is invalid") from exc
    if header.get("alg") != "ES256":
        raise PlaidWebhookVerificationError("verification algorithm is invalid")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise PlaidWebhookVerificationError("verification key id is missing")

    key = _verification_key(settings, kid)
    try:
        claims = jwt.decode(
            signed_jwt,
            key,
            algorithms=["ES256"],
            options={"verify_aud": False, "verify_exp": False, "require": ["iat"]},
        )
    except jwt.PyJWTError as exc:
        raise PlaidWebhookVerificationError("verification signature is invalid") from exc

    issued_at = claims.get("iat")
    if not isinstance(issued_at, (int, float)):
        raise PlaidWebhookVerificationError("verification timestamp is invalid")
    current = int(time.time()) if now is None else now
    if abs(current - int(issued_at)) > 300:
        raise PlaidWebhookVerificationError("verification token is outside the replay window")

    expected_hash = claims.get("request_body_sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise PlaidWebhookVerificationError("verification body hash is invalid")
    actual_hash = hashlib.sha256(raw_body).hexdigest()
    if not hmac.compare_digest(actual_hash, expected_hash):
        raise PlaidWebhookVerificationError("webhook body does not match its signature")
    return claims
