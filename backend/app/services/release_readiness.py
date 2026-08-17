from __future__ import annotations

from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.operations import operations_status, schema_versions
from app.services.plaid import production_readiness
from app.services.security_audit import security_posture

Status = Literal["pass", "warn", "fail"]

PROVIDER_IDENTIFIER_COLUMNS = (
    ("accounts", "external_id"),
    ("financial_institutions", "external_id"),
    ("plaid_items", "external_id"),
    ("transactions", "external_id"),
    ("transactions", "pending_transaction_external_id"),
)


def _check(name: str, status: Status, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _provider_identifier_collation(db: Session) -> dict[str, str]:
    if db.bind is None or db.bind.dialect.name != "mysql":
        return _check(
            "provider_identifier_collation",
            "pass",
            "Provider identifier collation verification is only required on MySQL",
        )

    try:
        database_name = db.execute(text("SELECT DATABASE()")).scalar_one_or_none()
        if not database_name:
            return _check(
                "provider_identifier_collation",
                "fail",
                "The active MySQL database name could not be determined",
            )

        rows = db.execute(
            text(
                """
                SELECT TABLE_NAME AS table_name,
                       COLUMN_NAME AS column_name,
                       COLLATION_NAME AS collation_name
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = :schema_name
                  AND (
                    (TABLE_NAME = 'accounts' AND COLUMN_NAME = 'external_id') OR
                    (TABLE_NAME = 'financial_institutions' AND COLUMN_NAME = 'external_id') OR
                    (TABLE_NAME = 'plaid_items' AND COLUMN_NAME = 'external_id') OR
                    (TABLE_NAME = 'transactions' AND COLUMN_NAME IN ('external_id', 'pending_transaction_external_id'))
                  )
                """
            ),
            {"schema_name": database_name},
        ).mappings().all()
    except Exception as exc:
        return _check(
            "provider_identifier_collation",
            "fail",
            f"Provider identifier collation could not be verified: {type(exc).__name__}",
        )
    observed = {
        (str(row["table_name"]), str(row["column_name"])): row["collation_name"]
        for row in rows
    }
    missing = [f"{table}.{column}" for table, column in PROVIDER_IDENTIFIER_COLUMNS if (table, column) not in observed]
    wrong = [
        f"{table}.{column}={observed[(table, column)]}"
        for table, column in PROVIDER_IDENTIFIER_COLUMNS
        if (table, column) in observed and observed[(table, column)] != "utf8mb4_bin"
    ]
    if missing or wrong:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if wrong:
            details.append("non-binary " + ", ".join(wrong))
        return _check(
            "provider_identifier_collation",
            "fail",
            "Plaid/provider identifiers are not fully case-sensitive: " + "; ".join(details),
        )
    return _check(
        "provider_identifier_collation",
        "pass",
        "All Plaid/provider identifier columns use utf8mb4_bin",
    )


def release_readiness(
    db: Session,
    settings: Settings,
    *,
    require_production: bool = False,
    strict_operations: bool = False,
) -> dict[str, object]:
    checks: list[dict[str, str]] = []

    if require_production:
        checks.append(
            _check(
                "production_environment",
                "pass" if settings.is_production and not settings.demo_mode else "fail",
                "Production mode is active and demo mode is disabled"
                if settings.is_production and not settings.demo_mode
                else "Release verification requires APP_ENV=production with DEMO_MODE=false",
            )
        )
    else:
        checks.append(
            _check(
                "production_environment",
                "pass" if settings.is_production else "warn",
                "Production mode is active"
                if settings.is_production
                else f"Release rehearsal is running in {settings.app_env} mode",
            )
        )

    try:
        db.execute(text("SELECT 1")).scalar_one()
    except Exception as exc:
        checks.append(
            _check("database_query", "fail", f"Database query failed: {type(exc).__name__}")
        )
        summary = {
            status: sum(1 for item in checks if item["status"] == status)
            for status in ("pass", "warn", "fail")
        }
        return {
            "ready": False,
            "environment": settings.app_env,
            "schema": {"current": None, "head": None},
            "checks": checks,
            "summary": summary,
            "security": None,
            "plaid": None,
            "operations": None,
        }
    else:
        checks.append(_check("database_query", "pass", "Database query succeeded"))

    current_schema, head_schema = schema_versions(db)
    if current_schema == head_schema:
        checks.append(_check("schema_current", "pass", f"Database schema is current at {head_schema}"))
    elif current_schema is None and not settings.is_production and not require_production:
        checks.append(
            _check(
                "schema_current",
                "warn",
                f"Migration state is unavailable in this local/test database; application head is {head_schema}",
            )
        )
    else:
        checks.append(
            _check(
                "schema_current",
                "fail",
                f"Database schema {current_schema or 'unknown'} does not match application head {head_schema}",
            )
        )

    checks.append(_provider_identifier_collation(db))

    security = security_posture(db, settings)
    security_summary = security["summary"]
    security_failures = int(security_summary["fail"])
    security_warnings = int(security_summary["warn"])
    checks.append(
        _check(
            "security_gate",
            "fail" if security_failures else ("warn" if security_warnings else "pass"),
            f"Security audit: {security_summary['pass']} pass, {security_warnings} warn, {security_failures} fail",
        )
    )

    plaid = production_readiness(db, settings)
    if require_production or settings.is_production:
        if settings.plaid_configured:
            plaid_status: Status = "pass" if bool(plaid["ready"]) else "fail"
            plaid_detail = (
                "Plaid Production readiness passed"
                if plaid_status == "pass"
                else "Plaid readiness issues: " + "; ".join(str(issue) for issue in plaid["issues"])
            )
        else:
            plaid_status = "fail"
            plaid_detail = "Plaid credentials are not configured for the production release"
    elif settings.plaid_configured:
        plaid_status = "pass" if bool(plaid["ready"]) else "warn"
        plaid_detail = (
            "Plaid Production readiness passed"
            if plaid_status == "pass"
            else "Plaid is configured for local rehearsal but is not production-ready: "
            + "; ".join(str(issue) for issue in plaid["issues"])
        )
    else:
        plaid_status = "warn"
        plaid_detail = "Plaid is not configured in this release rehearsal environment"
    checks.append(_check("plaid_production", plaid_status, plaid_detail))

    operations = operations_status(db, settings)
    jobs = operations["jobs"]
    failed_jobs = [name for name, item in jobs.items() if item["status"] == "failed"]
    attention_jobs = [name for name, item in jobs.items() if item["status"] == "attention"]
    if failed_jobs:
        operation_status: Status = "fail"
        operation_detail = "Operational jobs failed: " + ", ".join(failed_jobs)
    elif strict_operations and attention_jobs:
        operation_status = "fail"
        operation_detail = "Operational jobs are stale/unverified: " + ", ".join(attention_jobs)
    elif attention_jobs:
        operation_status = "warn"
        operation_detail = "Operational jobs need attention before production cutover: " + ", ".join(attention_jobs)
    else:
        operation_status = "pass"
        operation_detail = "Operational job history is healthy or intentionally disabled"
    checks.append(_check("operations_gate", operation_status, operation_detail))

    summary = {
        status: sum(1 for item in checks if item["status"] == status)
        for status in ("pass", "warn", "fail")
    }
    return {
        "ready": summary["fail"] == 0,
        "environment": settings.app_env,
        "schema": {"current": current_schema, "head": head_schema},
        "checks": checks,
        "summary": summary,
        "security": security,
        "plaid": plaid,
        "operations": operations,
    }
