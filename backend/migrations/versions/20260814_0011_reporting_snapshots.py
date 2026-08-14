"""Add daily financial snapshots for reports.

Revision ID: 20260814_0011
Revises: 20260814_0010
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0011"
down_revision: str | None = "20260814_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("net_worth", sa.Numeric(19, 4), nullable=False),
        sa.Column("cash_available", sa.Numeric(19, 4), nullable=False),
        sa.Column("planned_income", sa.Numeric(19, 4), nullable=False),
        sa.Column("actual_income", sa.Numeric(19, 4), nullable=False),
        sa.Column("budgeted", sa.Numeric(19, 4), nullable=False),
        sa.Column("spent", sa.Numeric(19, 4), nullable=False),
        sa.Column("safe_to_spend", sa.Numeric(19, 4), nullable=False),
        sa.Column("planning_commitments", sa.Numeric(19, 4), nullable=False),
        sa.Column("goal_reserves", sa.Numeric(19, 4), nullable=False),
        sa.Column("total_goal_target", sa.Numeric(19, 4), nullable=False),
        sa.Column("total_goal_current", sa.Numeric(19, 4), nullable=False),
        sa.Column("monthly_goal_contributions", sa.Numeric(19, 4), nullable=False),
        sa.Column("total_debt", sa.Numeric(19, 4), nullable=False),
        sa.Column("planned_monthly_debt_payment", sa.Numeric(19, 4), nullable=False),
        sa.Column("reserve_balance", sa.Numeric(19, 4), nullable=False),
        sa.Column("projected_30_day", sa.Numeric(19, 4), nullable=False),
        sa.Column("projected_60_day", sa.Numeric(19, 4), nullable=False),
        sa.Column("projected_90_day", sa.Numeric(19, 4), nullable=False),
        sa.Column("planned_debt_free_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "snapshot_date", name="uq_financial_snapshot_user_date"),
    )
    op.create_index(
        "ix_financial_snapshots_user_date",
        "financial_snapshots",
        ["user_id", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_financial_snapshots_user_date", table_name="financial_snapshots")
    op.drop_table("financial_snapshots")
