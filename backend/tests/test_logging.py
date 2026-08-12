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
    )
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "values %s and %s",
        (prefix, longer),
        None,
    )
    assert SecretRedactionFilter(settings).filter(record)
    message = record.getMessage()
    assert prefix not in message
    assert longer not in message
    assert "long-session-suffix" not in message
