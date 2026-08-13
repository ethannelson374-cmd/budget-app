from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app import cli as cli_module
from app.cli import _guard_demo_settings, migrate, reset_demo, reset_password
from app.core.config import Settings
from app.core.database import Database
from app.core.security import verify_password
from app.models import Account, AuditEvent, SessionRecord, Transaction, User
from app.services.auth import issue_session


def test_demo_guard_refuses_memory_non_demo_and_production(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        _guard_demo_settings(
            Settings(
                _env_file=None,
                app_env="test",
                demo_mode=True,
                demo_db_path=Path(":memory:"),
            )
        )
    with pytest.raises(RuntimeError):
        _guard_demo_settings(Settings(_env_file=None, app_env="development", demo_mode=False))
    with pytest.raises(RuntimeError):
        _guard_demo_settings(
            Settings(
                _env_file=None,
                app_env="development",
                demo_mode=True,
                demo_db_path=tmp_path / "budget.db",
            )
        )


def test_demo_guard_accepts_dedicated_disk_sqlite(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        demo_mode=True,
        demo_db_path=tmp_path / "demo.db",
    )
    _guard_demo_settings(settings)
    assert (tmp_path).is_dir()


def test_migrate_uses_explicit_settings(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / "explicit.db",
    )
    migrate(settings)
    assert (tmp_path / "explicit.db").exists()


def test_demo_reset_never_seeds_future_transactions(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        demo_mode=True,
        demo_db_path=tmp_path / "phase1-demo.db",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
    )
    reset_demo(settings)
    database = Database.from_settings(settings)
    try:
        with database.session_factory() as session:
            latest = session.scalar(select(func.max(Transaction.posted_date)))
            count = session.scalar(select(func.count(Transaction.id)))
            account_sources = set(session.scalars(select(Account.source_type)).all())
            transaction_sources = set(session.scalars(select(Transaction.source_type)).all())
        assert latest is not None
        assert latest <= datetime.now(ZoneInfo("America/Chicago")).date()
        assert count is not None and count > 0
        assert account_sources == {"plaid"}
        assert transaction_sources == {"plaid"}
    finally:
        database.engine.dispose()


def test_interactive_password_reset_rehashes_and_revokes_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        demo_mode=True,
        demo_db_path=tmp_path / "password-reset-demo.db",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
    )
    reset_demo(settings)
    database = Database.from_settings(settings)
    try:
        with database.session_factory() as session:
            user = session.scalar(select(User).where(User.normalized_username == "demo"))
            assert user is not None
            _, _, record = issue_session(session, settings, user, client_ip="127.0.0.1")
            session.commit()
            session_id = record.id

        monkeypatch.setattr(cli_module.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        answers = iter(["NewDemoPassword!2026", "NewDemoPassword!2026"])
        monkeypatch.setattr(cli_module.getpass, "getpass", lambda _prompt: next(answers))
        reset_password(settings, "demo")

        with database.session_factory() as session:
            user = session.scalar(select(User).where(User.normalized_username == "demo"))
            record = session.get(SessionRecord, session_id)
            reset_event = session.scalar(
                select(AuditEvent).where(AuditEvent.action == "auth.password_reset")
            )
            assert user is not None
            assert verify_password(user.password_hash, "NewDemoPassword!2026")[0]
            assert record is not None and record.revoked_at is not None
            assert reset_event is not None and reset_event.detail == "interactive_cli"
    finally:
        database.engine.dispose()
