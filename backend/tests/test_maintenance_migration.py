from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.config import Settings
from app.core.database import create_database_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_stage6_indexes_match_housekeeping_and_stable_transaction_order(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / "stage6-migration.db",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["settings"] = settings
    command.upgrade(config, "head")

    engine = create_database_engine(settings)
    try:
        inspector = inspect(engine)
        transaction_indexes = {
            row["name"]: row["column_names"] for row in inspector.get_indexes("transactions")
        }
        assert transaction_indexes["ix_transactions_user_posted"] == [
            "user_id",
            "posted_date",
            "id",
        ]

        assert "ix_sessions_revoked" in {row["name"] for row in inspector.get_indexes("sessions")}
        invitation_indexes = {row["name"] for row in inspector.get_indexes("user_invitations")}
        assert "ix_user_invitations_expires" in invitation_indexes
        reset_indexes = {row["name"] for row in inspector.get_indexes("password_reset_tokens")}
        assert "ix_password_reset_expires" in reset_indexes
        throttle_indexes = {row["name"] for row in inspector.get_indexes("login_throttles")}
        assert "ix_login_throttles_updated" in throttle_indexes
        export_indexes = {row["name"] for row in inspector.get_indexes("report_exports")}
        assert "ix_report_exports_created" in export_indexes
    finally:
        engine.dispose()
