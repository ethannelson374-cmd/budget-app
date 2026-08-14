from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import OperationalJob, PlaidItem, User

BACKEND_ROOT = Path(__file__).resolve().parents[2]
JOB_BACKUP = "database_backup"
JOB_BACKUP_VERIFY = "backup_verify"
JOB_PLAID_SYNC = "plaid_sync"
JOB_REPORT_SNAPSHOT = "report_snapshot"
KNOWN_JOBS = (JOB_BACKUP, JOB_BACKUP_VERIFY, JOB_PLAID_SYNC, JOB_REPORT_SNAPSHOT)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _json_summary(summary: dict[str, Any] | None) -> str:
    return json.dumps(summary or {}, separators=(",", ":"), sort_keys=True)


def record_job_started(db: Session, key: str) -> None:
    row = db.get(OperationalJob, key)
    if row is None:
        row = OperationalJob(key=key)
        db.add(row)
    row.status = "running"
    row.last_started_at = _utc_now()
    row.last_finished_at = None
    row.error_code = None
    row.summary_json = "{}"
    db.commit()


def record_job_finished(
    db: Session,
    key: str,
    *,
    success: bool,
    summary: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> None:
    row = db.get(OperationalJob, key)
    if row is None:
        row = OperationalJob(key=key)
        db.add(row)
    now = _utc_now()
    row.status = "success" if success else "failed"
    row.last_finished_at = now
    if success:
        row.last_success_at = now
        row.error_code = None
    else:
        row.error_code = (error_code or "operation_failed")[:120]
    row.summary_json = _json_summary(summary)
    db.commit()


def safe_job_summary(row: OperationalJob | None) -> dict[str, Any]:
    if row is None:
        return {
            "status": "never",
            "last_started_at": None,
            "last_finished_at": None,
            "last_success_at": None,
            "error_code": None,
            "summary": {},
        }
    try:
        summary = json.loads(row.summary_json)
        if not isinstance(summary, dict):
            summary = {}
    except json.JSONDecodeError:
        summary = {}
    return {
        "status": row.status,
        "last_started_at": row.last_started_at,
        "last_finished_at": row.last_finished_at,
        "last_success_at": row.last_success_at,
        "error_code": row.error_code,
        "summary": summary,
    }


def schema_versions(db: Session) -> tuple[str | None, str]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()
    current: str | None = None
    try:
        current = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        # Test databases created directly from metadata do not have alembic_version.
        current = None
    return current, head


def _age_hours(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return round(max((now - value.astimezone(UTC)).total_seconds(), 0) / 3600, 1)


def _job_state(
    row: OperationalJob | None,
    *,
    now: datetime,
    stale_after_hours: float | None = None,
    disabled: bool = False,
) -> dict[str, Any]:
    if disabled:
        return {
            "status": "disabled",
            "last_started_at": None,
            "last_finished_at": None,
            "last_success_at": None,
            "age_hours": None,
            "error_code": None,
            "summary": {},
        }
    item = safe_job_summary(row)
    age = _age_hours(item["last_success_at"], now)
    status = item["status"]
    if status == "never":
        status = "attention"
    elif status == "failed":
        status = "failed"
    elif status == "running":
        status = "running"
    elif stale_after_hours is not None and (age is None or age > stale_after_hours):
        status = "attention"
    else:
        status = "healthy"
    return {**item, "status": status, "age_hours": age}


def operations_status(db: Session, settings: Settings) -> dict[str, Any]:
    now = _utc_now()
    rows = {
        row.key: row
        for row in db.scalars(select(OperationalJob).where(OperationalJob.key.in_(KNOWN_JOBS))).all()
    }
    current_schema, head_schema = schema_versions(db)
    schema_current = (
        current_schema == head_schema if current_schema is not None else not settings.is_production
    )
    users = int(db.scalar(select(func.count(User.id))) or 0)
    active_plaid = int(
        db.scalar(select(func.count(PlaidItem.id)).where(PlaidItem.status == "active")) or 0
    )

    backup = _job_state(
        rows.get(JOB_BACKUP), now=now, stale_after_hours=float(settings.backup_max_age_hours)
    )
    backup_verify = _job_state(rows.get(JOB_BACKUP_VERIFY), now=now, stale_after_hours=24 * 8)
    snapshot = _job_state(
        rows.get(JOB_REPORT_SNAPSHOT),
        now=now,
        stale_after_hours=26,
        disabled=users == 0,
    )
    plaid = _job_state(
        rows.get(JOB_PLAID_SYNC),
        now=now,
        stale_after_hours=2,
        disabled=not settings.plaid_configured or active_plaid == 0,
    )

    backup_dir = settings.backup_dir.expanduser()
    backup_count = 0
    backup_bytes = 0
    try:
        if backup_dir.exists():
            archives = [
                path
                for path in backup_dir.iterdir()
                if path.is_file() and path.name.startswith("budget-") and path.suffix == ".gz"
            ]
            backup_count = len(archives)
            backup_bytes = sum(p.stat().st_size for p in archives)
        usage = shutil.disk_usage(backup_dir if backup_dir.exists() else backup_dir.parent)
        free_bytes: int | None = usage.free
    except OSError:
        free_bytes = None

    attention = []
    if not schema_current:
        attention.append("Database schema is not at the application migration head.")
    for label, item in (
        ("Database backup", backup),
        ("Backup verification", backup_verify),
        ("Reporting snapshot", snapshot),
        ("Plaid sync", plaid),
    ):
        if item["status"] == "failed":
            attention.append(f"{label} last run failed.")
        elif item["status"] == "attention":
            attention.append(f"{label} has not completed successfully within its expected window.")

    return {
        "generated_at": now,
        "overall": "healthy" if not attention else "attention",
        "database": {"status": "healthy"},
        "migration": {
            "status": "healthy" if schema_current else "attention",
            "current": current_schema,
            "head": head_schema,
        },
        "jobs": {
            "database_backup": backup,
            "backup_verify": backup_verify,
            "report_snapshot": snapshot,
            "plaid_sync": plaid,
        },
        "backup_storage": {
            "path": str(backup_dir),
            "archive_count": backup_count,
            "archive_bytes": backup_bytes,
            "free_bytes": free_bytes,
        },
        "attention": attention,
    }
