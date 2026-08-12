"""Create the Phase 1 application schema.

Revision ID: 20260812_0001
Revises:
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


money = sa.Numeric(19, 4)


def upgrade() -> None:
    op.create_table(
        "installation_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_installation_state"),
    )
    op.bulk_insert(
        sa.table(
            "installation_state",
            sa.column("id", sa.Integer()),
            sa.column("initialized_at", sa.DateTime(timezone=True)),
        ),
        [{"id": 1, "initialized_at": None}],
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("normalized_username", sa.String(80), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("normalized_email", name="uq_users_normalized_email"),
        sa.UniqueConstraint("normalized_username", name="uq_users_normalized_username"),
    )

    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("theme", sa.String(10), nullable=False),
        sa.Column("annual_gross_income", money, nullable=True),
        sa.Column("pay_frequency", sa.String(20), nullable=True),
        sa.Column("onboarding_complete", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "pay_frequency IS NULL OR pay_frequency IN "
            "('weekly','biweekly','semimonthly','monthly','annual')",
            name="pay_frequency_allowed",
        ),
        sa.CheckConstraint("theme IN ('light','dark','system')", name="theme_allowed"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_settings_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_settings"),
    )

    op.create_table(
        "login_throttles",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_login_throttles"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("csrf_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_key", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("token_digest", name="uq_sessions_token_digest"),
    )
    op.create_index("ix_sessions_idle_expires", "sessions", ["idle_expires_at"])
    op.create_index("ix_sessions_user_expires", "sessions", ["user_id", "absolute_expires_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("subject_key", sa.String(64), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_audit_events_user_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_created_action", "audit_events", ["created_at", "action"])

    op.create_table(
        "financial_institutions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_financial_institutions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_institutions"),
        sa.UniqueConstraint("id", "user_id", name="uq_institution_id_user"),
        sa.UniqueConstraint("user_id", "external_id", name="uq_institution_external"),
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stable_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("icon", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_categories_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("id", "user_id", name="uq_category_id_user"),
        sa.UniqueConstraint("user_id", "stable_key", name="uq_category_user_key"),
    )
    op.create_index("ix_categories_user_enabled", "categories", ["user_id", "enabled"])

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("institution_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("official_name", sa.String(255), nullable=True),
        sa.Column("account_type", sa.String(20), nullable=False),
        sa.Column("account_subtype", sa.String(40), nullable=True),
        sa.Column("current_balance", money, nullable=False),
        sa.Column("available_balance", money, nullable=True),
        sa.Column("credit_limit", money, nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("mask_last4", sa.String(4), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "account_type IN ('depository','credit','loan','investment','other')",
            name="account_type_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id", "user_id"],
            ["financial_institutions.id", "financial_institutions.user_id"],
            name="fk_account_institution_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_accounts_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
        sa.UniqueConstraint("id", "user_id", name="uq_account_id_user"),
        sa.UniqueConstraint("user_id", "external_id", name="uq_account_external"),
    )
    op.create_index("ix_accounts_user_type", "accounts", ["user_id", "account_type"])

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("posted_date", sa.Date(), nullable=False),
        sa.Column("authorized_date", sa.Date(), nullable=True),
        sa.Column("merchant", sa.String(160), nullable=True),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("amount", money, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("pending", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('income','expense','transfer','refund')",
            name="kind_allowed",
        ),
        sa.CheckConstraint(
            "(kind IN ('income','refund') AND amount >= 0) "
            "OR (kind = 'expense' AND amount <= 0) OR kind = 'transfer'",
            name="amount_sign",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            name="fk_transaction_account_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_transaction_category_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_transactions_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.UniqueConstraint("account_id", "external_id", name="uq_transaction_account_external"),
    )
    op.create_index(
        "ix_transactions_user_account_posted",
        "transactions",
        ["user_id", "account_id", "posted_date"],
    )
    op.create_index(
        "ix_transactions_user_category_posted",
        "transactions",
        ["user_id", "category_id", "posted_date"],
    )
    op.create_index("ix_transactions_user_posted", "transactions", ["user_id", "posted_date"])


def downgrade() -> None:
    op.drop_index("ix_transactions_user_posted", table_name="transactions")
    op.drop_index("ix_transactions_user_category_posted", table_name="transactions")
    op.drop_index("ix_transactions_user_account_posted", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_accounts_user_type", table_name="accounts")
    op.drop_table("accounts")
    op.drop_index("ix_categories_user_enabled", table_name="categories")
    op.drop_table("categories")
    op.drop_table("financial_institutions")
    op.drop_index("ix_audit_created_action", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_sessions_user_expires", table_name="sessions")
    op.drop_index("ix_sessions_idle_expires", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("login_throttles")
    op.drop_table("user_settings")
    op.drop_table("users")
    op.drop_table("installation_state")
