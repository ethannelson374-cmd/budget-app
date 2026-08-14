from __future__ import annotations

import logging

from app.core.config import Settings
from app.main import SecretRedactionFilter


def test_secret_filter_handles_overlapping_values() -> None:
    prefix = "overlapping-secret-prefix-value-"
    longer = prefix + "long-session-suffix"
    settings = Settings(
        _env_file=None,
        app_secret=prefix,
        session_secret=longer,
        encryption_key="independent-encryption-secret-value",
        plaid_client_id="plaid-client-id-secret-value",
        plaid_secret="plaid-api-secret-value",
        plaid_redirect_uri="https://budget.example.com/plaid/oauth",
    )
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "values %s and %s and %s",
        (prefix, longer, "plaid-api-secret-value"),
        None,
    )
    assert SecretRedactionFilter(settings).filter(record)
    message = record.getMessage()
    assert prefix not in message
    assert longer not in message
    assert "long-session-suffix" not in message
    assert "plaid-api-secret-value" not in message


def test_json_formatter_emits_request_correlation_fields() -> None:
    import json

    from app.main import JsonFormatter

    record = logging.LogRecord("budget.api", logging.INFO, __file__, 1, "request", (), None)
    record.request_id = "request-123"
    record.method = "GET"
    record.path = "/api/v1/operations/status"
    record.status = 200
    record.duration_ms = 12.5
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "request"
    assert payload["request_id"] == "request-123"
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/v1/operations/status"
    assert payload["status"] == 200
    assert payload["duration_ms"] == 12.5
