from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text

from app.core.config import Settings
from app.core.database import create_database_engine

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MYSQL_FIELDS = ("HOST", "PORT", "NAME", "USER", "PASSWORD", "SSL_REQUIRED")
MYSQL_OPTIONAL_FIELDS = ("SSL_MODE", "SSL_CA")


def mysql_test_settings(environ: Mapping[str, str]) -> Settings | None:
    """Build guarded MySQL settings without ever accepting a production schema."""

    if environ.get("RUN_MYSQL_INTEGRATION") != "true":
        return None

    has_test_values = any(environ.get(f"TEST_DB_{field}") for field in MYSQL_FIELDS)
    prefix = "TEST_DB_" if has_test_values else "DB_"
    values = {field: environ.get(f"{prefix}{field}") for field in MYSQL_FIELDS}
    optional = {field: environ.get(f"{prefix}{field}") for field in MYSQL_OPTIONAL_FIELDS}
    missing = [f"{prefix}{field}" for field, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "MySQL integration was enabled but required settings are missing: " + ", ".join(missing)
        )

    schema_name = values["NAME"] or ""
    if not schema_name.endswith("_test"):
        raise RuntimeError("MySQL integration DB_NAME must end with '_test'")
    if values["SSL_REQUIRED"] != "true":
        raise RuntimeError("MySQL integration DB_SSL_REQUIRED must be the literal value 'true'")

    return Settings(
        _env_file=None,
        app_env="development",
        demo_mode=False,
        db_host=values["HOST"],
        db_port=values["PORT"],
        db_name=schema_name,
        db_user=values["USER"],
        db_password=values["PASSWORD"],
        db_ssl_required=values["SSL_REQUIRED"],
        db_ssl_mode=optional["SSL_MODE"] or "REQUIRED",
        db_ssl_ca=optional["SSL_CA"] or None,
    )


def schema_object_count(connection: Connection, schema_name: str) -> int:
    value = connection.scalar(
        text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = :schema_name"),
        {"schema_name": schema_name},
    )
    return int(value or 0)


def alembic_configuration(settings: Settings) -> Config:
    configuration = Config(str(BACKEND_ROOT / "alembic.ini"))
    configuration.attributes["settings"] = settings
    return configuration


def test_mysql_guard_is_skip_by_default_and_rejects_unsafe_schema() -> None:
    assert mysql_test_settings({}) is None
    unsafe = {
        "RUN_MYSQL_INTEGRATION": "true",
        "DB_HOST": "mysql.internal.example",
        "DB_PORT": "3306",
        "DB_NAME": "budget",
        "DB_USER": "budgetapp",
        "DB_PASSWORD": "secret",
        "DB_SSL_REQUIRED": "true",
    }
    with pytest.raises(RuntimeError, match="must end with '_test'"):
        mysql_test_settings(unsafe)
    unsafe["DB_NAME"] = "budget_test"
    unsafe["DB_SSL_REQUIRED"] = "false"
    with pytest.raises(RuntimeError, match="literal value 'true'"):
        mysql_test_settings(unsafe)


@pytest.mark.mysql_integration
def test_mysql_migrations_and_tls_on_empty_test_schema() -> None:
    settings = mysql_test_settings(os.environ)
    if settings is None:
        pytest.skip(
            "Set RUN_MYSQL_INTEGRATION=true and complete TEST_DB_* (or DB_*) settings "
            "to run the guarded MySQL migration/TLS test"
        )

    schema_name = settings.db_name
    assert schema_name is not None and schema_name.endswith("_test")
    assert settings.db_ssl_required is True
    configuration = alembic_configuration(settings)
    engine = create_database_engine(settings)
    migration_started = False
    primary_error: BaseException | None = None
    try:
        assert engine.url.get_backend_name() == "mysql"
        with engine.connect() as connection:
            connected_schema = connection.scalar(text("SELECT DATABASE()"))
            assert connected_schema == schema_name
            assert schema_object_count(connection, schema_name) == 0, (
                "MySQL integration requires an existing, completely empty disposable schema"
            )
            cipher_row = connection.execute(text("SHOW SESSION STATUS LIKE 'Ssl_cipher'")).one()
            assert cipher_row[1], "MySQL connection did not report a negotiated TLS cipher"

        engine.dispose()
        migration_started = True
        command.upgrade(configuration, "head")
        command.check(configuration)

        engine = create_database_engine(settings)
        with engine.connect() as connection:
            assert schema_object_count(connection, schema_name) > 0
            cipher_row = connection.execute(text("SHOW SESSION STATUS LIKE 'Ssl_cipher'")).one()
            assert cipher_row[1]
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        engine.dispose()
        if migration_started:
            try:
                command.downgrade(configuration, "base")
                cleanup_engine = create_database_engine(settings)
                try:
                    with cleanup_engine.connect() as connection:
                        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
                        connection.commit()
                        assert schema_object_count(connection, schema_name) == 0
                finally:
                    cleanup_engine.dispose()
            except BaseException as cleanup_error:
                if primary_error is None:
                    raise
                primary_error.add_note(
                    "MySQL test-schema cleanup also failed: " + type(cleanup_error).__name__
                )
