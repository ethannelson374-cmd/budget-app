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


def test_plaid_environment_migration_marks_existing_items_as_sandbox(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / "plaid-migration.db",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
    )
    config = _alembic_config(settings)
    command.upgrade(config, "20260815_0016")
    engine = create_database_engine(settings)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, username, normalized_username, email, normalized_email,
                        password_hash, is_admin, email_verified_at, created_at, updated_at
                    ) VALUES (
                        1, 'owner', 'owner', 'owner@example.test', 'owner@example.test',
                        'hash', 1, :now, :now, :now
                    )
                    """
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO plaid_items (
                        id, user_id, institution_id, external_id, access_token_ciphertext,
                        access_token_nonce, status, created_at, updated_at
                    ) VALUES (
                        1, 1, NULL, 'item-existing', 'ciphertext', 'nonce', 'active', :now, :now
                    )
                    """
                ),
                {"now": now},
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT environment, update_required, update_reason, last_webhook_at "
                    "FROM plaid_items WHERE id = 1"
                )
            ).one()
            assert row.environment == "sandbox"
            assert row.update_required in (0, False)
            assert row.update_reason is None
            assert row.last_webhook_at is None
    finally:
        engine.dispose()
