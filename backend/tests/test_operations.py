from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cli import reset_demo
from app.core.config import Settings
from app.core.database import Database
from app.models import OperationalJob, User
from app.services.backups import create_backup, restore_test_backup, verify_backup
from app.services.operations import JOB_BACKUP, operations_status, record_job_finished, record_job_started
from tests.conftest import csrf_headers


def reliability_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="development",
        demo_mode=True,
        demo_db_path=tmp_path / "reliability-demo.db",
        backup_dir=tmp_path / "backups",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
    )


def test_sqlite_backup_is_compressed_checksummed_and_full_restore_tested(tmp_path: Path) -> None:
    settings = reliability_settings(tmp_path)
    reset_demo(settings)

    created = create_backup(settings)
    assert created["database_type"] == "sqlite"
    assert created["archive"].endswith(".sqlite3.gz")
    archive = settings.backup_dir / str(created["archive"])
    assert archive.exists()
    assert archive.with_name(f"{archive.name}.json").exists()

    verified = verify_backup(settings)
    assert verified["verification"] == "full_sqlite_restore"
    assert verified["sha256"] == created["sha256"]

    restored = restore_test_backup(settings)
    assert restored["restore_test"] == "passed"
    assert restored["target"] == "temporary_sqlite"


def test_operational_job_status_tracks_success_without_storing_exception_text(tmp_path: Path) -> None:
    settings = reliability_settings(tmp_path)
    reset_demo(settings)
    database = Database.from_settings(settings)
    try:
        with database.session_factory() as db:
            record_job_started(db, JOB_BACKUP)
            record_job_finished(db, JOB_BACKUP, success=True, summary={"size": 123})
            row = db.get(OperationalJob, JOB_BACKUP)
            assert row is not None
            assert row.status == "success"
            assert row.last_success_at is not None
            status = operations_status(db, settings)
            assert status["jobs"]["database_backup"]["status"] == "healthy"
            assert status["jobs"]["database_backup"]["summary"] == {"size": 123}
    finally:
        database.engine.dispose()


def test_operations_status_is_admin_only(
    authenticated: tuple[TestClient, str], database: Database
) -> None:
    client, csrf = authenticated
    response = client.get("/api/v1/operations/status")
    assert response.status_code == 200
    assert response.json()["database"]["status"] == "healthy"

    with database.session_factory() as db:
        user = db.scalar(select(User))
        assert user is not None
        user.is_admin = False
        db.commit()

    forbidden = client.get("/api/v1/operations/status", headers=csrf_headers(csrf))
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "admin_required"
