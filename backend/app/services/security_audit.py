from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, secret_has_256_bits
from app.models import InstallationState
from app.services.operations import schema_versions

Status = Literal["pass", "warn", "fail"]


def _check(name: str, status: Status, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _explicit_hosts(settings: Settings) -> dict[str, str]:
    wildcards = [host for host in settings.host_list if "*" in host]
    if wildcards:
        return _check("explicit_hosts", "fail" if settings.is_production else "warn", "Wildcard hosts are configured")
    return _check("explicit_hosts", "pass", "Only explicit request hostnames are allowed")


def _production_secrets(settings: Settings) -> dict[str, str]:
    values = [settings.app_secret, settings.session_secret, settings.encryption_key]
    if any(value is None for value in values):
        return _check("application_secrets", "fail" if settings.is_production else "warn", "One or more application secrets are not configured")
    material = [value.get_secret_value() for value in values if value is not None]
    if any(not secret_has_256_bits(value) for value in material):
        return _check("application_secrets", "fail" if settings.is_production else "warn", "Application secrets do not meet the 256-bit generation policy")
    if len(set(material)) != len(material):
        return _check("application_secrets", "fail", "Application secrets are not independent")
    return _check("application_secrets", "pass", "Independent 256-bit application secrets are configured")


def _public_url(settings: Settings) -> dict[str, str]:
    if settings.public_app_url is None:
        return _check("public_app_url", "warn" if settings.is_production else "pass", "PUBLIC_APP_URL is not configured")
    parsed = urlsplit(settings.public_app_url)
    if settings.is_production and parsed.scheme != "https":
        return _check("public_app_url", "fail", "The public application URL is not HTTPS")
    return _check("public_app_url", "pass", "The public application URL uses the expected scheme")


def _database_tls(settings: Settings) -> dict[str, str]:
    if settings.demo_mode or settings.app_env == "test":
        return _check("database_tls", "pass", "SQLite demo/test database does not traverse the network")
    if settings.db_ssl_required is not True:
        return _check("database_tls", "fail", "Database TLS is not required")
    if settings.db_ssl_mode == "VERIFY_IDENTITY":
        return _check("database_tls", "pass", "Database TLS verifies the CA chain and server identity")
    if settings.db_ssl_mode == "VERIFY_CA":
        return _check(
            "database_tls",
            "fail" if settings.is_production else "warn",
            "Database TLS verifies the CA chain but not the hostname",
        )
    return _check(
        "database_tls",
        "fail" if settings.is_production else "warn",
        "Database traffic is encrypted, but the server certificate identity is not verified",
    )


def _schema(db: Session) -> dict[str, str]:
    current, head = schema_versions(db)
    if current is None:
        return _check("schema_current", "warn", f"Migration state is unavailable; application head is {head}")
    if current != head:
        return _check("schema_current", "fail", f"Database schema {current} does not match application head {head}")
    return _check("schema_current", "pass", f"Database schema is current at {head}")


def _bootstrap(db: Session, settings: Settings) -> dict[str, str]:
    state = db.get(InstallationState, 1)
    initialized = bool(state and state.initialized_at is not None)
    if initialized and settings.bootstrap_token is not None:
        return _check("bootstrap_credential", "fail" if settings.is_production else "warn", "BOOTSTRAP_TOKEN is still configured after initialization")
    if initialized:
        return _check("bootstrap_credential", "pass", "One-time bootstrap credential is absent after initialization")
    return _check("bootstrap_credential", "warn", "Installation is not initialized yet")


def _database_grants(db: Session) -> dict[str, str]:
    if db.bind is None or db.bind.dialect.name != "mysql":
        return _check("database_grants", "pass", "Grant review is not applicable to this database")
    try:
        rows = db.execute(text("SHOW GRANTS FOR CURRENT_USER")).all()
    except Exception:
        return _check("database_grants", "warn", "Current database grants could not be inspected")
    grant_lines = [str(value).upper() for row in rows for value in row]
    grants = "\n".join(grant_lines)
    risky = []
    if any(" ON *.* " in line and not line.startswith("GRANT USAGE ON *.*") for line in grant_lines):
        risky.append("global privileges")
    if "ALL PRIVILEGES" in grants:
        risky.append("ALL PRIVILEGES")
    if "GRANT OPTION" in grants:
        risky.append("GRANT OPTION")
    if risky:
        return _check("database_grants", "warn", "Database credential has broad authority: " + ", ".join(dict.fromkeys(risky)))
    return _check("database_grants", "pass", "No global/all/grant-option authority was detected")


def _path_permissions(name: str, path: Path, *, production: bool) -> dict[str, str]:
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        return _check(name, "warn" if production else "pass", f"{path} is not present in this environment")
    if mode & 0o007:
        return _check(name, "fail" if production else "warn", f"{path} is accessible to other users (mode {mode:03o})")
    if mode & 0o020:
        return _check(name, "warn", f"{path} is group-writable (mode {mode:03o})")
    return _check(name, "pass", f"{path} is not accessible to other users (mode {mode:03o})")


def security_posture(db: Session, settings: Settings) -> dict[str, object]:
    checks: list[dict[str, str]] = [
        _check(
            "production_mode",
            "pass" if settings.is_production else "warn",
            "Production safeguards are active" if settings.is_production else f"Running in {settings.app_env} mode",
        ),
        _check(
            "demo_disabled",
            "pass" if not settings.is_production or not settings.demo_mode else "fail",
            "Demo mode is disabled in production" if settings.is_production else "Demo-mode policy is not production-critical",
        ),
        _production_secrets(settings),
        _explicit_hosts(settings),
        _public_url(settings),
        _database_tls(settings),
        _schema(db),
        _bootstrap(db, settings),
        _database_grants(db),
    ]
    if settings.is_production:
        checks.extend(
            [
                _path_permissions("environment_file_permissions", Path("/etc/budget-app/budget.env"), production=True),
                _path_permissions("backup_directory_permissions", settings.backup_dir, production=True),
            ]
        )

    counts = {status: sum(1 for item in checks if item["status"] == status) for status in ("pass", "warn", "fail")}
    return {
        "ready": counts["fail"] == 0,
        "environment": settings.app_env,
        "checks": checks,
        "summary": counts,
    }
