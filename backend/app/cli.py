from __future__ import annotations

import argparse
import calendar
import getpass
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.database import Database, build_database_url
from app.core.security import hash_password, normalize_identity, utc_now
from app.models import (
    Account,
    AnnualBudgetCategory,
    AnnualBudgetMonthAllocation,
    AnnualBudgetPlan,
    AuditEvent,
    Category,
    Debt,
    DebtStrategySettings,
    FinancialGoal,
    FinancialInstitution,
    FinancialSnapshot,
    ForecastAssumptions,
    GoalContribution,
    InstallationState,
    LoginThrottle,
    MonthlyBudget,
    MonthlyBudgetCategory,
    OperationalJob,
    PlaidItem,
    SessionRecord,
    Transaction,
    User,
    UserSettings,
)
from app.services.auth import add_audit_event, revoke_user_sessions
from app.services.backups import BackupError, create_backup, restore_test_backup, verify_backup
from app.services.catalog import DEFAULT_CATEGORIES
from app.services.operations import (
    JOB_BACKUP,
    JOB_BACKUP_VERIFY,
    JOB_PLAID_SYNC,
    JOB_REPORT_SNAPSHOT,
    JOB_NOTIFICATIONS,
    operations_status,
    record_job_finished,
    record_job_started,
)
from app.services.plaid_transactions import sync_all_plaid_items
from app.services.notifications import scan_all_notifications
from app.services.reports import capture_all_snapshots

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def migrate(settings: Settings | None = None) -> None:
    configuration = Config(str(BACKEND_ROOT / "alembic.ini"))
    if settings is not None:
        configuration.attributes["settings"] = settings
    command.upgrade(configuration, "head")


def _month_date(anchor: date, offset: int, day: int) -> date:
    absolute_month = anchor.year * 12 + anchor.month - 1 + offset
    year, zero_based_month = divmod(absolute_month, 12)
    month = zero_based_month + 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _guard_demo_settings(settings: Settings) -> None:
    url = build_database_url(settings)
    if settings.is_production or not settings.demo_mode or url.get_backend_name() != "sqlite":
        raise RuntimeError(
            "Demo reset is permitted only for an explicit non-production SQLite demo"
        )
    database_path = Path(url.database or "")
    if str(database_path) == ":memory:":
        raise RuntimeError("Demo reset requires a dedicated on-disk SQLite database")
    if database_path.name in {"", ".", ".."}:
        raise RuntimeError("The demo database path is not safe")
    if "demo" not in database_path.stem.casefold() or database_path.suffix.casefold() not in {
        ".db",
        ".sqlite",
        ".sqlite3",
    }:
        raise RuntimeError("Demo reset requires a dedicated database filename containing 'demo'")
    database_path.parent.mkdir(parents=True, exist_ok=True)


def reset_demo(settings: Settings) -> None:
    _guard_demo_settings(settings)
    migrate(settings)
    database = Database.from_settings(settings)
    now = utc_now()
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    try:
        with database.session_factory() as db:
            for model in (
                GoalContribution,
                FinancialSnapshot,
                Debt,
                DebtStrategySettings,
                FinancialGoal,
                ForecastAssumptions,
                AnnualBudgetMonthAllocation,
                AnnualBudgetCategory,
                MonthlyBudgetCategory,
                MonthlyBudget,
                AnnualBudgetPlan,
                Transaction,
                Account,
                PlaidItem,
                FinancialInstitution,
                Category,
                OperationalJob,
                SessionRecord,
                LoginThrottle,
                AuditEvent,
                UserSettings,
                User,
            ):
                db.execute(delete(model))
            state = db.get(InstallationState, 1)
            if state is None:
                state = InstallationState(id=1)
                db.add(state)

            user = User(
                username="demo",
                normalized_username="demo",
                email="demo@budget.local",
                normalized_email="demo@budget.local",
                password_hash=hash_password("DemoPassword!2026"),
                is_admin=True,
                email_verified_at=now,
                settings=UserSettings(
                    currency="USD",
                    timezone="America/Chicago",
                    theme="system",
                    annual_gross_income=Decimal("78000.0000"),
                    pay_frequency="biweekly",
                    onboarding_complete=True,
                ),
            )
            db.add(user)
            db.flush()

            categories: dict[str, Category] = {}
            for definition in DEFAULT_CATEGORIES:
                category = Category(
                    user_id=user.id,
                    stable_key=definition["key"],
                    name=definition["name"],
                    icon=definition["icon"],
                    enabled=True,
                )
                db.add(category)
                categories[definition["key"]] = category
            db.flush()

            annual_plan = AnnualBudgetPlan(
                user_id=user.id,
                year=today.year,
                planned_income=Decimal("54000.0000"),
                notes="Demo annual plan",
            )
            db.add(annual_plan)
            db.flush()
            demo_budget_amounts = {
                "housing": "17400.0000",
                "utilities": "2400.0000",
                "groceries": "7200.0000",
                "restaurants": "2400.0000",
                "gas": "2400.0000",
                "subscriptions": "240.0000",
                "debt_payments": "3900.0000",
                "shopping": "1800.0000",
                "entertainment": "1200.0000",
                "savings": "6000.0000",
            }
            for key, amount in demo_budget_amounts.items():
                db.add(
                    AnnualBudgetCategory(
                        plan_id=annual_plan.id,
                        user_id=user.id,
                        category_id=categories[key].id,
                        annual_amount=Decimal(amount),
                        distribution="even",
                        rollover_mode="surplus" if key in {"groceries", "shopping", "entertainment"} else "off",
                    )
                )
            db.flush()

            institution = FinancialInstitution(
                user_id=user.id,
                external_id="demo-institution",
                name="Demo Community Credit Union",
            )
            db.add(institution)
            db.flush()
            accounts = {
                "checking": Account(
                    user_id=user.id,
                    institution_id=institution.id,
                    external_id="demo-checking",
                    source_type="plaid",
                    name="Everyday Checking",
                    official_name="Everyday Checking Account",
                    account_type="depository",
                    account_subtype="checking",
                    current_balance=Decimal("3240.5200"),
                    available_balance=Decimal("3090.5200"),
                    credit_limit=None,
                    currency="USD",
                    mask_last4="1842",
                    last_synced_at=now,
                ),
                "savings": Account(
                    user_id=user.id,
                    institution_id=institution.id,
                    external_id="demo-savings",
                    source_type="plaid",
                    name="Emergency Savings",
                    official_name="High Yield Savings",
                    account_type="depository",
                    account_subtype="savings",
                    current_balance=Decimal("12850.0000"),
                    available_balance=Decimal("12850.0000"),
                    credit_limit=None,
                    currency="USD",
                    mask_last4="9027",
                    last_synced_at=now,
                ),
                "credit": Account(
                    user_id=user.id,
                    institution_id=institution.id,
                    external_id="demo-credit",
                    source_type="plaid",
                    name="Rewards Card",
                    official_name="Rewards Signature Card",
                    account_type="credit",
                    account_subtype="credit card",
                    current_balance=Decimal("-680.2400"),
                    available_balance=Decimal("7319.7600"),
                    credit_limit=Decimal("8000.0000"),
                    currency="USD",
                    mask_last4="4416",
                    last_synced_at=now,
                ),
                "loan": Account(
                    user_id=user.id,
                    institution_id=institution.id,
                    external_id="demo-loan",
                    source_type="plaid",
                    name="Auto Loan",
                    official_name="Vehicle Installment Loan",
                    account_type="loan",
                    account_subtype="auto",
                    current_balance=Decimal("-8200.0000"),
                    available_balance=None,
                    credit_limit=None,
                    currency="USD",
                    mask_last4="7319",
                    last_synced_at=now,
                ),
            }
            db.add_all(accounts.values())
            db.flush()

            db.add_all(
                [
                    FinancialGoal(
                        user_id=user.id,
                        linked_account_id=accounts["savings"].id,
                        name="Emergency fund",
                        goal_type="emergency_fund",
                        target_amount=Decimal("18000.0000"),
                        current_amount=Decimal("0"),
                        monthly_contribution=Decimal("500.0000"),
                        priority=10,
                        active=True,
                        notes="Six months of core expenses",
                    ),
                    FinancialGoal(
                        user_id=user.id,
                        name="House down payment",
                        goal_type="down_payment",
                        target_amount=Decimal("25000.0000"),
                        current_amount=Decimal("4200.0000"),
                        monthly_contribution=Decimal("650.0000"),
                        priority=20,
                        active=True,
                    ),
                    Debt(
                        user_id=user.id,
                        linked_account_id=accounts["loan"].id,
                        name="Auto loan",
                        debt_type="auto",
                        balance=Decimal("8200.0000"),
                        apr=Decimal("7.2000"),
                        minimum_payment=Decimal("325.0000"),
                        extra_payment=Decimal("75.0000"),
                        strategy_priority=20,
                        due_day=20,
                        active=True,
                    ),
                    Debt(
                        user_id=user.id,
                        linked_account_id=accounts["credit"].id,
                        name="Rewards card",
                        debt_type="credit_card",
                        balance=Decimal("680.2400"),
                        apr=Decimal("22.9900"),
                        minimum_payment=Decimal("45.0000"),
                        extra_payment=Decimal("25.0000"),
                        strategy_priority=10,
                        due_day=16,
                        active=True,
                    ),
                    DebtStrategySettings(
                        user_id=user.id,
                        strategy="avalanche",
                        monthly_extra_budget=Decimal("100.0000"),
                    ),
                    ForecastAssumptions(
                        user_id=user.id,
                        reserve_balance=Decimal("1500.0000"),
                        include_budget_reserve=True,
                    ),
                ]
            )
            db.flush()

            def transaction(
                suffix: str,
                posted: date,
                account_key: str,
                category_key: str,
                merchant: str,
                description: str,
                amount: str,
                kind: str,
                *,
                pending: bool = False,
            ) -> None:
                if posted > today:
                    return
                db.add(
                    Transaction(
                        user_id=user.id,
                        account_id=accounts[account_key].id,
                        category_id=categories[category_key].id,
                        external_id=f"demo-{suffix}",
                        source_type="plaid",
                        posted_date=posted,
                        authorized_date=posted,
                        merchant=merchant,
                        description=description,
                        amount=Decimal(amount),
                        kind=kind,
                        pending=pending,
                        imported_at=now,
                    )
                )

            for offset in range(-5, 1):
                month_key = _month_date(today.replace(day=1), offset, 1).strftime("%Y%m")
                transaction(
                    f"pay-1-{month_key}",
                    _month_date(today, offset, 1),
                    "checking",
                    "income",
                    "Northstar Software",
                    "Payroll direct deposit",
                    "2250.0000",
                    "income",
                )
                transaction(
                    f"rent-{month_key}",
                    _month_date(today, offset, 3),
                    "checking",
                    "housing",
                    "Oak Street Apartments",
                    "Monthly rent",
                    "-1450.0000",
                    "expense",
                )
                transaction(
                    f"groceries-1-{month_key}",
                    _month_date(today, offset, 7),
                    "credit",
                    "groceries",
                    "Fresh Market",
                    "Weekly groceries",
                    str(Decimal("-112.50") - Decimal(abs(offset) * 3)),
                    "expense",
                )
                transaction(
                    f"gas-{month_key}",
                    _month_date(today, offset, 10),
                    "credit",
                    "gas",
                    "QuickFuel",
                    "Fuel",
                    "-58.4200",
                    "expense",
                )
                transaction(
                    f"dining-{month_key}",
                    _month_date(today, offset, 12),
                    "credit",
                    "restaurants",
                    "Juniper Kitchen",
                    "Dinner",
                    str(Decimal("-74.30") - Decimal(abs(offset) * 2)),
                    "expense",
                )
                transaction(
                    f"subscription-{month_key}",
                    _month_date(today, offset, 14),
                    "credit",
                    "subscriptions",
                    "Streambox",
                    "Monthly streaming plan",
                    "-15.9900",
                    "expense",
                )
                transaction(
                    f"pay-2-{month_key}",
                    _month_date(today, offset, 15),
                    "checking",
                    "income",
                    "Northstar Software",
                    "Payroll direct deposit",
                    "2250.0000",
                    "income",
                )
                transaction(
                    f"utilities-{month_key}",
                    _month_date(today, offset, 18),
                    "checking",
                    "utilities",
                    "City Utilities",
                    "Electric, water, and waste",
                    str(Decimal("-168.00") - Decimal(abs(offset) * 4)),
                    "expense",
                )
                transaction(
                    f"loan-{month_key}",
                    _month_date(today, offset, 20),
                    "checking",
                    "debt_payments",
                    "Demo Community Credit Union",
                    "Auto loan payment",
                    "-325.0000",
                    "expense",
                )
                transaction(
                    f"groceries-2-{month_key}",
                    _month_date(today, offset, 21),
                    "credit",
                    "groceries",
                    "Neighborhood Foods",
                    "Weekly groceries",
                    "-96.1800",
                    "expense",
                )
                transaction(
                    f"transfer-out-{month_key}",
                    _month_date(today, offset, 22),
                    "checking",
                    "transfers",
                    "Transfer",
                    "Transfer to savings",
                    "-300.0000",
                    "transfer",
                )
                transaction(
                    f"transfer-in-{month_key}",
                    _month_date(today, offset, 22),
                    "savings",
                    "transfers",
                    "Transfer",
                    "Transfer from checking",
                    "300.0000",
                    "transfer",
                )

            transaction(
                "grocery-refund-current",
                _month_date(today, 0, 23),
                "credit",
                "groceries",
                "Fresh Market",
                "Grocery return",
                "23.5000",
                "refund",
            )
            transaction(
                "pending-grocery-current",
                today,
                "credit",
                "groceries",
                "Fresh Market",
                "Pending groceries",
                "-67.1400",
                "expense",
                pending=True,
            )

            state.initialized_at = now
            add_audit_event(
                db,
                settings,
                action="demo.reset",
                outcome="success",
                request_id=None,
                user_id=user.id,
            )
            db.commit()
    finally:
        database.engine.dispose()


def reset_password(settings: Settings, username: str) -> None:
    if not sys.stdin.isatty():
        raise RuntimeError("Password reset requires an interactive terminal")
    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain between 12 and 128 characters")

    database = Database.from_settings(settings)
    try:
        with database.session_factory() as db:
            user = db.scalar(
                select(User)
                .options(selectinload(User.settings))
                .where(User.normalized_username == normalize_identity(username))
                .with_for_update()
            )
            if user is None:
                raise LookupError("No matching user was found")
            user.password_hash = hash_password(password)
            revoke_user_sessions(db, user.id)
            add_audit_event(
                db,
                settings,
                action="auth.password_reset",
                outcome="success",
                request_id=None,
                user_id=user.id,
                detail="interactive_cli",
            )
            db.commit()
    finally:
        database.engine.dispose()



def sync_plaid(settings: Settings, item_id: int | None = None) -> dict[str, int]:
    database = Database.from_settings(settings)
    try:
        with database.session_factory() as db:
            return sync_all_plaid_items(db, settings, item_id=item_id)
    finally:
        database.engine.dispose()



def snapshot_reports(settings: Settings) -> dict[str, int]:
    database = Database.from_settings(settings)
    try:
        with database.session_factory() as db:
            return capture_all_snapshots(db)
    finally:
        database.engine.dispose()


def _record_job(
    settings: Settings,
    key: str,
    *,
    started: bool,
    success: bool = False,
    summary: dict[str, object] | None = None,
    error_code: str | None = None,
) -> None:
    database = Database.from_settings(settings)
    try:
        with database.session_factory() as db:
            if started:
                record_job_started(db, key)
            else:
                record_job_finished(
                    db, key, success=success, summary=summary, error_code=error_code
                )
    finally:
        database.engine.dispose()


def _tracked(settings: Settings, key: str, operation):
    _record_job(settings, key, started=True)
    try:
        result = operation()
        failed = result.get("failed", 0) if isinstance(result, dict) else 0
        success = not bool(failed)
        _record_job(
            settings,
            key,
            started=False,
            success=success,
            summary=result if isinstance(result, dict) else {},
        )
        return result
    except Exception as exc:
        try:
            _record_job(
                settings,
                key,
                started=False,
                success=False,
                error_code=type(exc).__name__[:120],
            )
        except Exception:
            pass
        raise


def run_notifications(settings: Settings, *, force_summaries: bool = False) -> dict[str, int]:
    database = Database.from_settings(settings)
    try:
        with database.session_factory() as db:
            return scan_all_notifications(db, settings, force_summaries=force_summaries)
    finally:
        database.engine.dispose()


def current_operations_status(settings: Settings) -> dict[str, object]:
    database = Database.from_settings(settings)
    try:
        with database.session_factory() as db:
            return operations_status(db, settings)
    finally:
        database.engine.dispose()


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(prog="python -m app.cli")
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("demo-reset", help="Migrate and rebuild the guarded demo database")
    reset = subcommands.add_parser(
        "reset-password", help="Interactively reset an owner password and revoke sessions"
    )
    reset.add_argument("--username", required=True, help="Owner username (password is prompted)")
    sync = subcommands.add_parser(
        "sync-plaid", help="Synchronize Plaid transactions for active bank connections"
    )
    sync.add_argument(
        "--item-id",
        type=int,
        help="Synchronize only one internal Plaid connection id",
    )
    subcommands.add_parser(
        "snapshot-reports", help="Capture or refresh today's reporting snapshot for every user"
    )
    subcommands.add_parser(
        "backup-db", help="Create a compressed logical database backup and apply retention"
    )
    subcommands.add_parser(
        "verify-backup", help="Verify the newest backup checksum, archive, and structure"
    )
    restore = subcommands.add_parser(
        "restore-test-backup", help="Restore-test the newest backup without touching the live database"
    )
    restore.add_argument(
        "--target-db-name",
        help="Existing empty MySQL database named budget_restore_*; SQLite uses a temporary target",
    )
    notify = subcommands.add_parser(
        "run-notifications", help="Generate deterministic financial notifications for every user"
    )
    notify.add_argument(
        "--force-summaries",
        action="store_true",
        help="Generate this period's weekly/monthly summaries even outside their normal schedule",
    )
    subcommands.add_parser(
        "operations-status", help="Print the admin-safe reliability status as JSON"
    )
    return command_parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = Settings()
    try:
        if args.command == "demo-reset":
            reset_demo(settings)
            print("Demo database migrated and reset successfully.")
        elif args.command == "reset-password":
            reset_password(settings, args.username)
            print("Password reset and active sessions revoked.")
        elif args.command == "sync-plaid":
            result = _tracked(settings, JOB_PLAID_SYNC, lambda: sync_plaid(settings, args.item_id))
            print(
                f"Plaid transaction sync complete: {result['succeeded']} succeeded, "
                f"{result['failed']} failed."
            )
            if result["failed"]:
                return 1
        elif args.command == "snapshot-reports":
            result = _tracked(settings, JOB_REPORT_SNAPSHOT, lambda: snapshot_reports(settings))
            print(
                f"Reporting snapshot capture complete: {result['succeeded']} succeeded, "
                f"{result['failed']} failed."
            )
            if result["failed"]:
                return 1
        elif args.command == "backup-db":
            result = _tracked(settings, JOB_BACKUP, lambda: create_backup(settings))
            print(
                f"Database backup created: {result['archive']} ({result['size']} bytes, "
                f"schema {result['schema_version']})."
            )
        elif args.command == "verify-backup":
            result = _tracked(settings, JOB_BACKUP_VERIFY, lambda: verify_backup(settings))
            print(
                f"Backup verified: {result['archive']} ({result['verification']}, "
                f"schema {result['schema_version']})."
            )
        elif args.command == "restore-test-backup":
            result = _tracked(
                settings,
                JOB_BACKUP_VERIFY,
                lambda: restore_test_backup(settings, args.target_db_name),
            )
            print(
                f"Backup restore test passed: {result['archive']} -> {result['target']} "
                f"(schema {result['schema_version']})."
            )
        elif args.command == "run-notifications":
            result = _tracked(
                settings,
                JOB_NOTIFICATIONS,
                lambda: run_notifications(settings, force_summaries=args.force_summaries),
            )
            print(
                f"Notification scan complete: {result['created']} created, "
                f"{result['emailed']} emailed, {result['failed']} failed users."
            )
            if result["failed"]:
                return 1
        elif args.command == "operations-status":
            print(json.dumps(current_operations_status(settings), default=str, indent=2))
    except (LookupError, RuntimeError, ValueError, BackupError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
