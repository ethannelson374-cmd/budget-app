"""Add per-account balance snapshots for Phase 5D trends.

Revision ID: 20260817_0021
Revises: 20260815_0020
Create Date: 2026-08-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0021"
down_revision: str | None = "20260815_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_balance_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("account_name", sa.String(120), nullable=False),
        sa.Column("institution_name", sa.String(160), nullable=True),
        sa.Column("account_type", sa.String(20), nullable=False),
        sa.Column("account_subtype", sa.String(40), nullable=True),
        sa.Column("source_type", sa.String(12), nullable=False),
        sa.Column("balance", sa.Numeric(19, 4), nullable=False),
        sa.Column("available_balance", sa.Numeric(19, 4), nullable=True),
        sa.Column("credit_limit", sa.Numeric(19, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "account_id", "snapshot_date",
            name="uq_account_balance_snapshot_user_account_date",
        ),
    )
    op.create_index(
        "ix_account_balance_snapshots_user_date",
        "account_balance_snapshots",
        ["user_id", "snapshot_date"],
    )
    op.create_index(
        "ix_account_balance_snapshots_user_account_date",
        "account_balance_snapshots",
        ["user_id", "account_id", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_balance_snapshots_user_account_date",
        table_name="account_balance_snapshots",
    )
    op.drop_index(
        "ix_account_balance_snapshots_user_date",
        table_name="account_balance_snapshots",
    )
    op.drop_table("account_balance_snapshots")
