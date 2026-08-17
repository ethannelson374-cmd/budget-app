from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import create_database_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(settings: Settings) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["settings"] = settings
    return config


def test_identity_migration_preserves_existing_sqlite_user_children(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / "migration.db",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
    )
    config = _alembic_config(settings)
    command.upgrade(config, "20260814_0012")

    engine = create_database_engine(settings)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, username, normalized_username, email, normalized_email,
                        password_hash, created_at, updated_at
                    ) VALUES (
                        1, 'demo', 'demo', 'demo@budget.local', 'demo@budget.local',
                        'hash', :now, :now
                    )
                    """
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO user_settings (
                        user_id, currency, timezone, theme, annual_gross_income,
                        pay_frequency, onboarding_complete, created_at, updated_at
                    ) VALUES (
                        1, 'USD', 'America/Chicago', 'system', 78000,
                        'biweekly', 1, :now, :now
                    )
                    """
                ),
                {"now": now},
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT currency, timezone, onboarding_complete, onboarding_step FROM user_settings WHERE user_id = 1")
            ).one()
            assert row.currency == "USD"
            assert row.timezone == "America/Chicago"
            assert bool(row.onboarding_complete) is True
            assert row.onboarding_step == 6
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    finally:
        engine.dispose()
