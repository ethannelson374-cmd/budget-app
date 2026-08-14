from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core import database as database_module
from app.core.config import Settings, bootstrap_token_has_256_bits
from app.core.database import (
    build_database_url,
    create_database_engine,
    create_ssl_context,
    verify_tls_cipher,
)


def production_values() -> dict[str, object]:
    return {
        "_env_file": None,
        "app_env": "production",
        "demo_mode": False,
        "app_secret": "a" * 64,
        "session_secret": "b" * 64,
        "encryption_key": "c" * 64,
        "db_host": "mysql.internal.example",
        "db_port": 3306,
        "db_name": "budget",
        "db_user": "budgetapp",
        "db_password": "database-secret-with-reserved:/@?#[]",
        "db_ssl_required": True,
        "allowed_hosts": "budget.example.com",
        "backup_dir": Path("/var/lib/budget-app/backups"),
    }


@pytest.mark.parametrize("value", ["3306.0", "+3306", "-1", " 3306 ", "port", 3306.0, True])
def test_database_port_is_strict(value: object) -> None:
    values = production_values()
    values["db_port"] = value
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.mark.parametrize("value", ["TRUE", "False", " true ", "1", "yes", 1])
def test_database_ssl_boolean_is_literal(value: object) -> None:
    values = production_values()
    values["db_ssl_required"] = value
    with pytest.raises(ValidationError):
        Settings(**values)


def test_production_requires_all_database_values_and_tls() -> None:
    for key in ("db_host", "db_port", "db_name", "db_user", "db_password", "db_ssl_required"):
        values = production_values()
        values[key] = None
        with pytest.raises(ValidationError):
            Settings(**values)


def test_production_rejects_demo_and_placeholder_secrets() -> None:
    values = production_values()
    values["demo_mode"] = True
    with pytest.raises(ValidationError):
        Settings(**values)
    values = production_values()
    values["app_secret"] = "<random-256-bit-value>"
    with pytest.raises(ValidationError):
        Settings(**values)


def test_production_accepts_existing_opaque_secret_values() -> None:
    values = production_values()
    values.update(
        app_secret="existing-app-secret",
        session_secret="existing-session-secret",
        encryption_key="existing-encryption-key",
    )
    settings = Settings(**values)
    assert settings.app_secret is not None
    assert settings.session_secret is not None
    assert settings.encryption_key is not None


def test_validation_error_never_contains_secret_input() -> None:
    sentinel = "NEVER-EXPOSE-THIS-SECRET-9f54f3f0"
    values = production_values()
    values.update(
        app_secret=sentinel,
        session_secret=sentinel + "-session",
        encryption_key=sentinel + "-encryption",
        db_password=sentinel + "-database",
        db_port="not-a-port",
    )
    with pytest.raises(ValidationError) as captured:
        Settings(**values)
    rendered = str(captured.value)
    assert sentinel not in rendered


def test_existing_secret_variables_are_accepted_and_redacted() -> None:
    settings = Settings(
        _env_file=None,
        app_secret="app-secret-sentinel",
        session_secret="session-secret-sentinel",
        encryption_key="encryption-key-sentinel",
    )
    rendered = repr(settings)
    assert "app-secret-sentinel" not in rendered
    assert "session-secret-sentinel" not in rendered
    assert "encryption-key-sentinel" not in rendered


def test_programmatic_url_preserves_reserved_password_and_ignores_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///rogue.db")
    values = production_values()
    settings = Settings(**values)
    url = build_database_url(settings)
    assert url.drivername == "mysql+pymysql"
    assert url.password == values["db_password"]
    assert url.host == "mysql.internal.example"
    assert url.query == {"charset": "utf8mb4"}
    assert "rogue.db" not in url.render_as_string(hide_password=False)


def test_sqlite_is_only_selected_for_demo_or_test(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        demo_mode=True,
        demo_db_path=tmp_path / "demo.db",
    )
    assert build_database_url(settings).get_backend_name() == "sqlite"
    with pytest.raises(RuntimeError):
        build_database_url(Settings(_env_file=None, app_env="development", demo_mode=False))


def test_database_ssl_mode_defaults_to_required() -> None:
    settings = Settings(**production_values())
    assert settings.db_ssl_mode == "REQUIRED"
    assert settings.db_ssl_ca is None


def test_database_ssl_mode_normalizes_and_rejects_unknown_values() -> None:
    values = production_values()
    values["db_ssl_mode"] = " verify_identity "
    values["db_ssl_ca"] = "/etc/budget-app/heatwave-ca.crt"
    settings = Settings(**values)
    assert settings.db_ssl_mode == "VERIFY_IDENTITY"

    values["db_ssl_mode"] = "disabled"
    with pytest.raises(ValidationError):
        Settings(**values)


def test_verification_modes_require_ca_in_production() -> None:
    for mode in ("VERIFY_CA", "VERIFY_IDENTITY"):
        values = production_values()
        values["db_ssl_mode"] = mode
        with pytest.raises(ValidationError, match="DB_SSL_CA is required"):
            Settings(**values)


def test_required_ssl_context_encrypts_without_certificate_validation() -> None:
    context = create_ssl_context(Settings(**production_values()))
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2


@pytest.mark.parametrize(
    ("mode", "check_hostname"),
    [("VERIFY_CA", False), ("VERIFY_IDENTITY", True)],
)
def test_verification_ssl_context_uses_explicit_ca(
    monkeypatch: pytest.MonkeyPatch, mode: str, check_hostname: bool
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_default_context(*, purpose: ssl.Purpose, cafile: str) -> ssl.SSLContext:
        captured.update(purpose=purpose, cafile=cafile)
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(database_module.ssl, "create_default_context", fake_create_default_context)
    values = production_values()
    values["db_ssl_mode"] = mode
    values["db_ssl_ca"] = "/etc/budget-app/heatwave-ca.crt"
    context = create_ssl_context(Settings(**values))

    assert captured == {
        "purpose": ssl.Purpose.SERVER_AUTH,
        "cafile": str(Path("/etc/budget-app/heatwave-ca.crt")),
    }
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is check_hostname
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2


def test_heatwave_pool_and_timeouts_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    sentinel = object()

    def fake_create_engine(url: object, **options: Any) -> object:
        captured.update(url=url, **options)
        return sentinel

    listeners: list[tuple[object, str]] = []
    monkeypatch.setattr(database_module, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        database_module.event,
        "listen",
        lambda target, event_name, _handler: listeners.append((target, event_name)),
    )

    engine = create_database_engine(Settings(**production_values()))
    assert engine is sentinel
    assert captured["pool_size"] == 2
    assert captured["max_overflow"] == 1
    assert captured["pool_timeout"] == 10
    assert captured["pool_recycle"] == 900
    assert captured["pool_pre_ping"] is True
    assert captured["pool_use_lifo"] is True
    connect_args = captured["connect_args"]
    assert connect_args["connect_timeout"] == 10
    assert connect_args["read_timeout"] == 30
    assert connect_args["write_timeout"] == 30
    assert isinstance(connect_args["ssl"], ssl.SSLContext)
    assert connect_args["ssl"].verify_mode == ssl.CERT_NONE
    assert connect_args["ssl"].check_hostname is False
    assert listeners == [(sentinel, "connect")]


def test_required_tls_connection_rejects_an_empty_cipher() -> None:
    class SocketWithoutCipher:
        @staticmethod
        def cipher() -> None:
            return None

    class ConnectionWithoutCipher:
        _sock = SocketWithoutCipher()

    with pytest.raises(ConnectionError, match="did not negotiate TLS"):
        verify_tls_cipher(ConnectionWithoutCipher())


def test_bootstrap_token_encoding_validation() -> None:
    assert bootstrap_token_has_256_bits("ab" * 32)
    assert bootstrap_token_has_256_bits("A" * 43)
    assert not bootstrap_token_has_256_bits("ab" * 31)
    assert not bootstrap_token_has_256_bits("not standard/base64+")


def test_windows_timezone_data_is_available() -> None:
    from zoneinfo import ZoneInfo

    assert ZoneInfo("America/Chicago").key == "America/Chicago"


def test_ai_provider_requires_only_selected_provider_key() -> None:
    openai = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        ai_enabled=True,
        ai_provider="openai",
        openai_api_key="openai-test-key",
    )
    assert openai.ai_configured is True
    assert openai.advisor_model == "gpt-5.6"

    gemini = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        ai_enabled=True,
        ai_provider="gemini",
        gemini_api_key="gemini-test-key",
    )
    assert gemini.ai_configured is True
    assert gemini.advisor_model == "gemini-3.6-flash"

    with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
        Settings(
            _env_file=None,
            app_env="test",
            demo_mode=True,
            ai_enabled=True,
            ai_provider="gemini",
        )
