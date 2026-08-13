"""Add Plaid connection and connected-account metadata for Phase 2B.

Revision ID: 20260813_0003
Revises: 20260813_0002
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0003"
down_revision: str | None = "20260813_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("financial_institutions") as batch_op:
        batch_op.add_column(sa.Column("logo_base64", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("primary_color", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("url", sa.String(512), nullable=True))

    op.create_table(
        "plaid_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("institution_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("access_token_nonce", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("consent_expiration_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','error')", name="plaid_item_status_allowed"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["institution_id", "user_id"],
            ["financial_institutions.id", "financial_institutions.user_id"],
            name="fk_plaid_item_institution_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_plaid_item_id_user"),
        sa.UniqueConstraint("user_id", "external_id", name="uq_plaid_item_external"),
    )
    op.create_index("ix_plaid_items_user_status", "plaid_items", ["user_id", "status"])

    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(sa.Column("plaid_item_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_account_plaid_item_owner",
            "plaid_items",
            ["plaid_item_id", "user_id"],
            ["id", "user_id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_accounts_user_plaid_item", ["user_id", "plaid_item_id"])


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_index("ix_accounts_user_plaid_item")
        batch_op.drop_constraint("fk_account_plaid_item_owner", type_="foreignkey")
        batch_op.drop_column("plaid_item_id")

    op.drop_index("ix_plaid_items_user_status", table_name="plaid_items")
    op.drop_table("plaid_items")

    with op.batch_alter_table("financial_institutions") as batch_op:
        batch_op.drop_column("url")
        batch_op.drop_column("primary_color")
        batch_op.drop_column("logo_base64")
