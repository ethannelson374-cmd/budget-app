"""Add financial goals, debt planning, and forecast assumptions.

Revision ID: 20260813_0007
Revises: 20260813_0006
Create Date: 2026-08-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0007"
down_revision: str | None = "20260813_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_goals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("linked_account_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("goal_type", sa.String(24), nullable=False, server_default="savings"),
        sa.Column("target_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("current_amount", sa.Numeric(19, 4), nullable=False, server_default="0"),
        sa.Column("monthly_contribution", sa.Numeric(19, 4), nullable=False, server_default="0"),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("id", "user_id", name="uq_financial_goal_id_user"),
        sa.UniqueConstraint(
            "user_id", "linked_account_id", name="uq_financial_goal_linked_account"
        ),
        sa.CheckConstraint(
            "goal_type IN ('emergency_fund','savings','down_payment','vacation',"
            "'purchase','custom')",
            name="financial_goal_type_allowed",
        ),
        sa.CheckConstraint("target_amount > 0", name="financial_goal_target_positive"),
        sa.CheckConstraint("current_amount >= 0", name="financial_goal_current_nonnegative"),
        sa.CheckConstraint("monthly_contribution >= 0", name="financial_goal_monthly_nonnegative"),
    )
    op.create_index(
        "ix_financial_goals_user_active",
        "financial_goals",
        ["user_id", "active", "priority"],
    )

    op.create_table(
        "goal_contributions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("contribution_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("notes", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["goal_id", "user_id"], ["financial_goals.id", "financial_goals.user_id"],
            name="fk_goal_contribution_goal_owner", ondelete="CASCADE"
        ),
        sa.CheckConstraint("amount > 0", name="goal_contribution_amount_positive"),
    )
    op.create_index(
        "ix_goal_contributions_user_date",
        "goal_contributions",
        ["user_id", "contribution_date"],
    )

    op.create_table(
        "debts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("linked_account_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("debt_type", sa.String(24), nullable=False, server_default="other"),
        sa.Column("balance", sa.Numeric(19, 4), nullable=False),
        sa.Column("apr", sa.Numeric(7, 4), nullable=False, server_default="0"),
        sa.Column("minimum_payment", sa.Numeric(19, 4), nullable=False, server_default="0"),
        sa.Column("extra_payment", sa.Numeric(19, 4), nullable=False, server_default="0"),
        sa.Column("strategy_priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("due_day", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("id", "user_id", name="uq_debt_id_user"),
        sa.UniqueConstraint("user_id", "linked_account_id", name="uq_debt_linked_account"),
        sa.CheckConstraint(
            "debt_type IN ('credit_card','auto','student','personal','mortgage','medical','other')",
            name="debt_type_allowed",
        ),
        sa.CheckConstraint("balance >= 0", name="debt_balance_nonnegative"),
        sa.CheckConstraint("apr >= 0 AND apr <= 100", name="debt_apr_range"),
        sa.CheckConstraint("minimum_payment >= 0", name="debt_minimum_nonnegative"),
        sa.CheckConstraint("extra_payment >= 0", name="debt_extra_nonnegative"),
        sa.CheckConstraint(
            "due_day IS NULL OR (due_day >= 1 AND due_day <= 31)",
            name="debt_due_day_range",
        ),
    )
    op.create_index("ix_debts_user_active", "debts", ["user_id", "active", "strategy_priority"])

    op.create_table(
        "debt_strategy_settings",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("strategy", sa.String(16), nullable=False, server_default="avalanche"),
        sa.Column("monthly_extra_budget", sa.Numeric(19, 4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "strategy IN ('avalanche','snowball','custom')",
            name="debt_strategy_allowed",
        ),
        sa.CheckConstraint("monthly_extra_budget >= 0", name="debt_strategy_extra_nonnegative"),
    )

    op.create_table(
        "forecast_assumptions",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("reserve_balance", sa.Numeric(19, 4), nullable=False, server_default="0"),
        sa.Column("include_budget_reserve", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("reserve_balance >= 0", name="forecast_reserve_nonnegative"),
    )


def downgrade() -> None:
    op.drop_table("forecast_assumptions")
    op.drop_table("debt_strategy_settings")
    op.drop_index("ix_debts_user_active", table_name="debts")
    op.drop_table("debts")
    op.drop_index("ix_goal_contributions_user_date", table_name="goal_contributions")
    op.drop_table("goal_contributions")
    op.drop_index("ix_financial_goals_user_active", table_name="financial_goals")
    op.drop_table("financial_goals")
