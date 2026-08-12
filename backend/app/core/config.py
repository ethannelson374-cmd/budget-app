from __future__ import annotations

import base64
import binascii
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
DatabaseSSLMode = Literal["REQUIRED", "VERIFY_CA", "VERIFY_IDENTITY"]


def _strict_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value == "true":
            return True
        if value == "false":
            return False
    raise ValueError("must be the literal value 'true' or 'false'")


def bootstrap_token_has_256_bits(value: str) -> bool:
    """Validate encodings suitable for a generated 256-bit bootstrap token.

    Accepted forms are 64 hexadecimal characters or an unpadded/padded base64url
    value that decodes to exactly 32 bytes. This validates encoded size; operators
    must still generate the token with a cryptographically secure generator.
    """

    if re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return True
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
        return False
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        canonical_length = len(value.rstrip("=")) == 43
        return canonical_length and len(decoded) == 32
    except (ValueError, binascii.Error):
        return False


class Settings(BaseSettings):
    """Environment-backed settings.

    The object intentionally ignores unknown environment values. In particular,
    DATABASE_URL is not declared, inspected, or used anywhere in the application.
    Secret values use Pydantic's redacted SecretStr representation.
    """

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
        hide_input_in_errors=True,
    )

    app_env: Environment = "development"
    demo_mode: bool = False
    demo_db_path: Path = Path("./data/demo.db")
    bootstrap_token: SecretStr | None = None
    allowed_hosts: str = "localhost,127.0.0.1"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    app_secret: SecretStr | None = None
    session_secret: SecretStr | None = None
    encryption_key: SecretStr | None = None

    db_host: str | None = None
    db_port: Annotated[int, Field(ge=1, le=65535)] | None = None
    db_name: str | None = None
    db_user: str | None = None
    db_password: SecretStr | None = None
    db_ssl_required: bool | None = None
    db_ssl_mode: DatabaseSSLMode = "REQUIRED"
    db_ssl_ca: Path | None = None

    @field_validator("demo_mode", "db_ssl_required", mode="before")
    @classmethod
    def validate_exact_boolean(cls, value: Any) -> bool | None:
        if value is None:
            return value
        return _strict_bool(value)

    @field_validator("db_ssl_mode", mode="before")
    @classmethod
    def normalize_database_ssl_mode(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_environment(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("db_port", mode="before")
    @classmethod
    def validate_strict_port(cls, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("must be a base-10 integer")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            return int(value)
        raise ValueError("must be a base-10 integer")

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, value: str) -> str:
        hosts = [host.strip() for host in value.split(",") if host.strip()]
        if not hosts:
            raise ValueError("must contain at least one host")
        if any("/" in host or "://" in host for host in hosts):
            raise ValueError("must contain hostnames only, not URLs or paths")
        return ",".join(hosts)

    @field_validator("db_host", "db_name", "db_user", "db_ssl_ca", mode="before")
    @classmethod
    def blank_string_is_missing(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "bootstrap_token",
        "app_secret",
        "session_secret",
        "encryption_key",
        "db_password",
        mode="before",
    )
    @classmethod
    def blank_secret_is_missing(cls, value: Any) -> Any:
        if isinstance(value, str) and not value:
            return None
        return value

    @model_validator(mode="after")
    def validate_environment_contract(self) -> Settings:
        if self.bootstrap_token is not None:
            token = self.bootstrap_token.get_secret_value()
            if token and not bootstrap_token_has_256_bits(token):
                raise ValueError(
                    "BOOTSTRAP_TOKEN must be a generated 256-bit value encoded as "
                    "64 hexadecimal characters or a 32-byte base64url value"
                )

        if self.app_env == "production":
            if self.demo_mode:
                raise ValueError("DEMO_MODE cannot be enabled in production")
            required_database = {
                "DB_HOST": self.db_host,
                "DB_PORT": self.db_port,
                "DB_NAME": self.db_name,
                "DB_USER": self.db_user,
                "DB_PASSWORD": self.db_password,
                "DB_SSL_REQUIRED": self.db_ssl_required,
            }
            missing_database = [name for name, value in required_database.items() if value is None]
            if missing_database:
                raise ValueError(
                    "production database configuration is incomplete: "
                    + ", ".join(missing_database)
                )
            if self.db_ssl_required is not True:
                raise ValueError("DB_SSL_REQUIRED must be true in production")
            if self.db_ssl_mode in {"VERIFY_CA", "VERIFY_IDENTITY"} and self.db_ssl_ca is None:
                raise ValueError(f"DB_SSL_CA is required when DB_SSL_MODE={self.db_ssl_mode}")
            required_secrets = {
                "APP_SECRET": self.app_secret,
                "SESSION_SECRET": self.session_secret,
                "ENCRYPTION_KEY": self.encryption_key,
            }
            missing_secrets = [name for name, value in required_secrets.items() if value is None]
            if missing_secrets:
                raise ValueError(
                    "production application secrets are incomplete: " + ", ".join(missing_secrets)
                )
            placeholder_secrets = [
                name
                for name, value in required_secrets.items()
                if value is not None
                and (
                    "<" in value.get_secret_value()
                    or ">" in value.get_secret_value()
                    or value.get_secret_value().casefold()
                    in {"changeme", "change-me", "replace-me", "development-only"}
                )
            ]
            if placeholder_secrets:
                raise ValueError(
                    "production application secrets must be non-placeholder values: "
                    + ", ".join(placeholder_secrets)
                )
        return self

    @property
    def host_list(self) -> list[str]:
        return self.allowed_hosts.split(",")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def secret_value(self, name: Literal["app_secret", "session_secret", "encryption_key"]) -> str:
        values: dict[
            Literal["app_secret", "session_secret", "encryption_key"], SecretStr | None
        ] = {
            "app_secret": self.app_secret,
            "session_secret": self.session_secret,
            "encryption_key": self.encryption_key,
        }
        value = values[name]
        if value is None:
            # Deterministic development/test-only key. Production validation makes
            # this branch unreachable in deployed environments.
            return f"budget-{self.app_env}-{name}-development-only"
        return value.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
