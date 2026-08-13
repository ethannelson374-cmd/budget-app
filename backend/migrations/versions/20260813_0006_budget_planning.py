"""Add annual and monthly budget planning.

Revision ID: 20260813_0006
Revises: 20260813_0005
Create Date: 2026-08-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0006"
down_revision: str | None = "20260813_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annual_budget_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("planned_income", sa.Numeric(19, 4), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", "user_id", name="uq_annual_budget_plan_id_user"),
        sa.UniqueConstraint("user_id", "year", name="uq_annual_budget_plan_user_year"),
        sa.CheckConstraint("year >= 2000 AND year <= 2200", name="annual_budget_plan_year_range"),
    )
    op.create_index(
        "ix_annual_budget_plans_user_year", "annual_budget_plans", ["user_id", "year"]
    )

    op.create_table(
        "annual_budget_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("annual_amount", sa.Numeric(19, 4), nullable=False, server_default="0"),
        sa.Column("distribution", sa.String(16), nullable=False, server_default="even"),
        sa.Column("monthly_amount", sa.Numeric(19, 4), nullable=True),
        sa.Column("rollover_mode", sa.String(24), nullable=False, server_default="off"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["annual_budget_plans.id", "annual_budget_plans.user_id"],
            name="fk_annual_budget_category_plan_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_annual_budget_category_category_owner",
        ),
        sa.UniqueConstraint(
            "plan_id", "category_id", name="uq_annual_budget_category_plan_category"
        ),
        sa.CheckConstraint(
            "distribution IN ('even','monthly','custom')",
            name="annual_budget_category_distribution_allowed",
        ),
        sa.CheckConstraint(
            "rollover_mode IN ('off','surplus','surplus_and_deficit')",
            name="annual_budget_category_rollover_allowed",
        ),
    )
    op.create_index(
        "ix_annual_budget_categories_user_plan",
        "annual_budget_categories",
        ["user_id", "plan_id"],
    )

    op.create_table(
        "annual_budget_month_allocations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("annual_category_id", sa.Integer(), nullable=False),
        sa.Column("month_number", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.ForeignKeyConstraint(
            ["annual_category_id"], ["annual_budget_categories.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "annual_category_id", "month_number", name="uq_annual_budget_month_allocation"
        ),
        sa.CheckConstraint(
            "month_number >= 1 AND month_number <= 12",
            name="annual_budget_month_number_range",
        ),
    )

    op.create_table(
        "monthly_budgets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="standalone"),
        sa.Column("planned_income", sa.Numeric(19, 4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", "user_id", name="uq_monthly_budget_id_user"),
        sa.UniqueConstraint("user_id", "month", name="uq_monthly_budget_user_month"),
        sa.CheckConstraint("mode IN ('standalone','override')", name="monthly_budget_mode_allowed"),
    )
    op.create_index("ix_monthly_budgets_user_month", "monthly_budgets", ["user_id", "month"])

    op.create_table(
        "monthly_budget_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("budget_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("planned_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("rollover_mode", sa.String(24), nullable=False, server_default="off"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["budget_id", "user_id"],
            ["monthly_budgets.id", "monthly_budgets.user_id"],
            name="fk_monthly_budget_category_budget_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_monthly_budget_category_category_owner",
        ),
        sa.UniqueConstraint(
            "budget_id", "category_id", name="uq_monthly_budget_category_budget_category"
        ),
        sa.CheckConstraint(
            "rollover_mode IN ('off','surplus','surplus_and_deficit')",
            name="monthly_budget_category_rollover_allowed",
        ),
    )
    op.create_index(
        "ix_monthly_budget_categories_user_budget",
        "monthly_budget_categories",
        ["user_id", "budget_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_monthly_budget_categories_user_budget", table_name="monthly_budget_categories")
    op.drop_table("monthly_budget_categories")
    op.drop_index("ix_monthly_budgets_user_month", table_name="monthly_budgets")
    op.drop_table("monthly_budgets")
    op.drop_table("annual_budget_month_allocations")
    op.drop_index("ix_annual_budget_categories_user_plan", table_name="annual_budget_categories")
    op.drop_table("annual_budget_categories")
    op.drop_index("ix_annual_budget_plans_user_year", table_name="annual_budget_plans")
    op.drop_table("annual_budget_plans")
