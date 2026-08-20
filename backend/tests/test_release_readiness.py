from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from app.cli import parser
from app.core.config import Settings
from app.core.database import Database, create_database_engine
from app.core.security import hash_password, normalize_identity, utc_now
from app.models import Account, BudgetMembership, Transaction, User
from app.services.release_readiness import release_readiness

BACKEND_ROOT = Path(__file__).resolve().parents[1]



def test_release_readiness_cli_exposes_production_and_strict_flags() -> None:
    args = parser().parse_args(
        ["release-readiness", "--require-production", "--strict-operations"]
    )
    assert args.command == "release-readiness"
    assert args.require_production is True
    assert args.strict_operations is True

def test_release_readiness_is_secret_free_and_local_rehearsal_can_pass(
    settings: Settings, database: Database
) -> None:
    with database.session_factory() as db:
        result = release_readiness(db, settings)

    assert result["ready"] is True
    assert result["summary"]["fail"] == 0
    rendered = repr(result)
    assert settings.secret_value("app_secret") not in rendered
    assert settings.secret_value("session_secret") not in rendered
    assert settings.secret_value("encryption_key") not in rendered
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["database_query"]["status"] == "pass"
    assert checks["provider_identifier_collation"]["status"] == "pass"



def test_release_readiness_local_sandbox_plaid_is_warning_not_failure(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        demo_mode=True,
        demo_db_path=tmp_path / "release-readiness-sandbox.db",
        allowed_hosts="localhost,127.0.0.1",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
        plaid_client_id="local-client",
        plaid_secret="local-secret",
        plaid_env="sandbox",
        plaid_redirect_uri="https://localhost/plaid/oauth",
        plaid_webhook_uri="https://localhost/api/v1/plaid/webhook",
    )
    database = Database.from_settings(settings)
    try:
        from app.models import Base

        Base.metadata.create_all(database.engine)
        with database.session_factory() as db:
            result = release_readiness(db, settings)
    finally:
        database.engine.dispose()

    checks = {item["name"]: item for item in result["checks"]}
    assert checks["plaid_production"]["status"] == "warn"
    assert result["summary"]["fail"] == 0
    assert result["ready"] is True

def test_phase5_upgrade_from_phase4_0020_preserves_financial_rows(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_mode=True,
        demo_db_path=tmp_path / "phase5-release-rehearsal.db",
        app_secret="a" * 64,
        session_secret="b" * 64,
        encryption_key="c" * 64,
    )
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["settings"] = settings
    command.upgrade(config, "20260815_0020")

    database = Database.from_settings(settings)
    try:
        with database.session_factory() as db:
            user = User(
                username="release-owner",
                normalized_username=normalize_identity("release-owner"),
                email="release@example.com",
                normalized_email=normalize_identity("release@example.com"),
                password_hash=hash_password("Release Rehearsal Password!2026"),
                is_admin=True,
            )
            db.add(user)
            db.flush()
            # This test deliberately parks the database at the Phase 4 schema.
            # Seed user_settings using the columns that existed at 0020 rather
            # than the current ORM model, which correctly includes later fields.
            now = utc_now()
            db.execute(
                text(
                    """
                    INSERT INTO user_settings (
                        user_id, currency, timezone, theme, annual_gross_income,
                        pay_frequency, onboarding_complete, advisor_enabled,
                        advisor_share_merchants, advisor_include_descriptions,
                        advisor_store_history, advisor_share_planning_names,
                        created_at, updated_at
                    ) VALUES (
                        :user_id, 'USD', 'America/Chicago', 'system', NULL, NULL,
                        :onboarding_complete, 1, 0, 0, 1, 0, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "user_id": user.id,
                    "onboarding_complete": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            account = Account(
                user_id=user.id,
                name="Phase 4 Checking",
                account_type="depository",
                account_subtype="checking",
                source_type="manual",
                current_balance=Decimal("4321.1000"),
                available_balance=Decimal("4200.1000"),
                currency="USD",
            )
            db.add(account)
            db.flush()
            transaction = Transaction(
                user_id=user.id,
                account_id=account.id,
                posted_date=date(2026, 8, 15),
                description="Phase 4 preserved transaction",
                amount=Decimal("-42.5000"),
                kind="expense",
                source_type="manual",
                pending=False,
                excluded_from_spending=False,
                imported_at=utc_now(),
            )
            db.add(transaction)
            db.commit()
            user_id, account_id, transaction_id = user.id, account.id, transaction.id
    finally:
        database.engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(settings)
    try:
        inspector = inspect(engine)
        assert "account_balance_snapshots" in inspector.get_table_names()
        with engine.connect() as connection:
            version = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
        assert version == "20260820_0023"
    finally:
        engine.dispose()

    database = Database.from_settings(settings)
    try:
        with database.session_factory() as db:
            user = db.get(User, user_id)
            account = db.get(Account, account_id)
            transaction = db.get(Transaction, transaction_id)
            assert user is not None and user.email == "release@example.com"
            assert user.settings is not None
            assert user.settings.onboarding_complete is True
            assert user.settings.onboarding_step == 6
            assert account is not None and account.current_balance == Decimal("4321.1000")
            assert transaction is not None and transaction.description == "Phase 4 preserved transaction"
            assert db.scalar(select(Transaction.id).where(Transaction.id == transaction_id)) == transaction_id
            membership = db.get(BudgetMembership, user_id)
            assert membership is not None
            assert membership.budget_owner_user_id == user_id
            assert membership.role == "owner"
    finally:
        database.engine.dispose()
