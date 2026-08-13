"""Add transaction intelligence, rules, recurring streams, and webhook sync hints.

Revision ID: 20260813_0005
Revises: 20260813_0004
Create Date: 2026-08-13
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0005"
down_revision: str | None = "20260813_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plaid_items") as batch_op:
        batch_op.add_column(sa.Column("sync_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("webhook_uri", sa.String(512), nullable=True))

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("user_category_override_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("display_merchant", sa.String(160), nullable=True))
        batch_op.add_column(sa.Column("user_kind_override", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("excluded_from_spending", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column("applied_rule_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_transaction_override_category_owner",
            "categories",
            ["user_category_override_id", "user_id"],
            ["id", "user_id"],
        )
    op.create_index("ix_transactions_user_override_category", "transactions", ["user_id", "user_category_override_id"])

    op.create_table(
        "transaction_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("match_field", sa.String(16), nullable=False, server_default="either"),
        sa.Column("pattern", sa.String(160), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("display_merchant", sa.String(160), nullable=True),
        sa.Column("kind_override", sa.String(20), nullable=True),
        sa.Column("excluded_from_spending", sa.Boolean(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"], ["categories.id", "categories.user_id"],
            name="fk_transaction_rule_category_owner",
        ),
        sa.CheckConstraint("match_field IN ('merchant','description','either')", name="transaction_rule_match_field_allowed"),
        sa.CheckConstraint("kind_override IS NULL OR kind_override IN ('income','expense','transfer','refund')", name="transaction_rule_kind_allowed"),
    )
    op.create_index("ix_transaction_rules_user_priority", "transaction_rules", ["user_id", "enabled", "priority"])

    op.create_table(
        "recurring_streams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("merchant_key", sa.String(160), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("cadence", sa.String(16), nullable=False),
        sa.Column("average_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("last_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("last_date", sa.Date(), nullable=False),
        sa.Column("next_expected_date", sa.Date(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("price_change_pct", sa.Numeric(9, 4), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id", "user_id"], ["accounts.id", "accounts.user_id"],
            name="fk_recurring_stream_account_owner", ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind IN ('income','expense')", name="recurring_stream_kind_allowed"),
        sa.CheckConstraint("cadence IN ('weekly','biweekly','monthly','quarterly','annual')", name="recurring_stream_cadence_allowed"),
        sa.UniqueConstraint("user_id", "account_id", "merchant_key", "kind", "cadence", name="uq_recurring_stream_identity"),
    )
    op.create_index("ix_recurring_streams_user_next", "recurring_streams", ["user_id", "active", "next_expected_date"])


def downgrade() -> None:
    op.drop_index("ix_recurring_streams_user_next", table_name="recurring_streams")
    op.drop_table("recurring_streams")
    op.drop_index("ix_transaction_rules_user_priority", table_name="transaction_rules")
    op.drop_table("transaction_rules")
    op.drop_index("ix_transactions_user_override_category", table_name="transactions")
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint("fk_transaction_override_category_owner", type_="foreignkey")
        batch_op.drop_column("applied_rule_id")
        batch_op.drop_column("excluded_from_spending")
        batch_op.drop_column("user_kind_override")
        batch_op.drop_column("display_merchant")
        batch_op.drop_column("user_category_override_id")
    with op.batch_alter_table("plaid_items") as batch_op:
        batch_op.drop_column("webhook_uri")
        batch_op.drop_column("sync_requested_at")
