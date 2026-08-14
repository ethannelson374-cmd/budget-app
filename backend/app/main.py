from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.errors import ApiError
from app.schemas.api import StatusView
from app.services.setup import ensure_installation_state, installation_initialized

logger = logging.getLogger("budget.api")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class SecretRedactionFilter(logging.Filter):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        candidates = [
            settings.bootstrap_token,
            settings.app_secret,
            settings.session_secret,
            settings.encryption_key,
            settings.db_password,
            settings.plaid_client_id,
            settings.plaid_secret,
            settings.openai_api_key,
            settings.gemini_api_key,
            settings.google_client_secret,
            settings.smtp_password,
        ]
        values = {
            value.get_secret_value()
            for value in candidates
            if value is not None and value.get_secret_value()
        }
        self.secrets = tuple(sorted(values, key=len, reverse=True))

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        record.msg = message
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    @staticmethod
    def converter(timestamp: float | None = None) -> time.struct_time:
        return time.gmtime(timestamp)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SecretRedactionFilter(settings))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(settings.log_level)
    logger.propagate = False


def error_body(request: Request, code: str, message: str) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", "unknown"),
        }
    }


def host_is_allowed(host: str | None, allowed_hosts: list[str]) -> bool:
    if not host:
        return False
    candidate = host.casefold().rstrip(".")
    for configured in allowed_hosts:
        allowed = configured.casefold().rstrip(".")
        if allowed == "*" or candidate == allowed:
            return True
        if allowed.startswith("*.") and candidate.endswith(allowed[1:]):
            return True
    return False


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if application.state.database is None:
            application.state.database = Database.from_settings(resolved_settings)
        db_object: Database = application.state.database
        with db_object.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        with db_object.session_factory() as session:
            ensure_installation_state(session)
            if (
                resolved_settings.is_production
                and not installation_initialized(session)
                and resolved_settings.bootstrap_token is None
            ):
                raise RuntimeError(
                    "Initial setup is unavailable until the one-time deployment "
                    "credential is configured"
                )
        yield
        if database is None:
            db_object.engine.dispose()

    application = FastAPI(
        title="Budget API",
        version="0.1.0",
        docs_url=None if resolved_settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if resolved_settings.is_production else "/api/openapi.json",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.database = database

    @application.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        inbound_id = request.headers.get("X-Request-ID", "")
        request_id = inbound_id if REQUEST_ID_PATTERN.fullmatch(inbound_id) else uuid.uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()
        response: Response
        if not host_is_allowed(request.url.hostname, resolved_settings.host_list):
            response = JSONResponse(
                status_code=400,
                content=error_body(request, "invalid_host", "The request host is not allowed"),
            )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        route_path = getattr(request.scope.get("route"), "path", None)
        if not isinstance(route_path, str):
            route_path = "unmatched"
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            route_path,
            response.status_code,
            round((perf_counter() - started) * 1000, 2),
            request_id,
        )
        return response

    @application.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, exc.code, exc.message),
            headers=exc.headers,
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            code, message = "not_found", "The requested endpoint was not found"
        elif exc.status_code == 405:
            code, message = "method_not_allowed", "The request method is not allowed"
        else:
            code, message = "http_error", "The request could not be completed"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, code, message),
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(request, "validation_error", "Request validation failed"),
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error(
            "database request failure type=%s request_id=%s",
            type(exc).__name__,
            getattr(request.state, "request_id", "unknown"),
        )
        return JSONResponse(
            status_code=503,
            content=error_body(
                request, "database_unavailable", "The database is temporarily unavailable"
            ),
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled request failure type=%s request_id=%s",
            type(exc).__name__,
            getattr(request.state, "request_id", "unknown"),
        )
        return JSONResponse(
            status_code=500,
            content=error_body(request, "internal_error", "An unexpected error occurred"),
        )

    @application.get("/api/health", tags=["health"], response_model=StatusView)
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @application.get("/api/ready", tags=["health"], response_model=StatusView)
    def ready(request: Request) -> dict[str, str]:
        db_object: Database = request.app.state.database
        try:
            with db_object.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            with db_object.session_factory() as session:
                initialized = installation_initialized(session)
            if (
                resolved_settings.is_production
                and not initialized
                and resolved_settings.bootstrap_token is None
            ):
                raise ApiError(
                    503,
                    "setup_unavailable",
                    "Initial setup is unavailable until deployment configuration is complete",
                )
        except ApiError:
            raise
        except (SQLAlchemyError, ConnectionError) as exc:
            raise ApiError(503, "database_unavailable", "The database is unavailable") from exc
        return {"status": "ready"}

    application.include_router(api_router)
    return application


app = create_app()
