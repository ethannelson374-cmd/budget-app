from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.config import Settings
from app.core.database import create_database_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_stage7_adds_private_planning_name_setting(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, app_env="test", demo_mode=True, demo_db_path=tmp_path / "stage7.db")
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["settings"] = settings
    command.upgrade(config, "head")
    engine = create_database_engine(settings)
    try:
        columns = {row["name"]: row for row in inspect(engine).get_columns("user_settings")}
        assert "advisor_share_planning_names" in columns
        assert columns["advisor_share_planning_names"]["nullable"] is False
    finally:
        engine.dispose()
