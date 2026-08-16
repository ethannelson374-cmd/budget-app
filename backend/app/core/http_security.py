from __future__ import annotations

from fastapi import Request
from starlette.responses import Response

from app.core.errors import ApiError

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def validate_request_metadata(request: Request, *, max_request_bytes: int, production: bool) -> None:
    """Apply cheap request guards before endpoint code sees the request.

    Nginx remains the public body-size boundary. These checks are defense in depth
    for accidental direct exposure and reject obviously cross-site unsafe browser
    requests before they reach authentication/CSRF/database work.
    """

    length = request.headers.get("Content-Length")
    if length:
        try:
            parsed = int(length, 10)
        except ValueError as exc:
            raise ApiError(400, "content_length_invalid", "The request size is invalid") from exc
        if parsed < 0:
            raise ApiError(400, "content_length_invalid", "The request size is invalid")
        if parsed > max_request_bytes:
            raise ApiError(413, "request_too_large", "The request body is too large")

    if request.method.upper() in UNSAFE_METHODS:
        fetch_site = request.headers.get("Sec-Fetch-Site", "").casefold()
        if fetch_site == "cross-site":
            raise ApiError(403, "cross_site_request", "Cross-site state-changing requests are blocked")

    # Internal loopback health/readiness probes do not carry proxy headers. If a
    # production reverse proxy does supply the header, it must assert HTTPS.
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    if production and forwarded_proto and forwarded_proto.casefold() != "https":
        raise ApiError(400, "https_required", "HTTPS is required")


def apply_api_security_headers(response: Response) -> None:
    """Keep API responses non-cacheable and harmless if rendered as content."""

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(), payment=(), usb=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
