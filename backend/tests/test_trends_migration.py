from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.config import Settings
from app.core.database import create_database_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_phase5d_adds_account_balance_snapshot_history(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / "phase5d.db",
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
        columns = {row["name"]: row for row in inspector.get_columns("account_balance_snapshots")}
        assert {"user_id", "account_id", "snapshot_date", "balance", "currency"}.issubset(columns)
        indexes = {row["name"]: row["column_names"] for row in inspector.get_indexes("account_balance_snapshots")}
        assert indexes["ix_account_balance_snapshots_user_date"] == ["user_id", "snapshot_date"]
        assert indexes["ix_account_balance_snapshots_user_account_date"] == ["user_id", "account_id", "snapshot_date"]
    finally:
        engine.dispose()
