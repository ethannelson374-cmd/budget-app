"""Add Advisor action proposals, deterministic previews, and undo history.

Revision ID: 20260814_0010
Revises: 20260813_0009
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0010"
down_revision: str | None = "20260813_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "advisor_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("preview_json", sa.Text(), nullable=False),
        sa.Column("precondition_json", sa.Text(), nullable=False),
        sa.Column("rollback_json", sa.Text(), nullable=False),
        sa.Column("applied_state_json", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["advisor_conversations.id", "advisor_conversations.user_id"],
            name="fk_advisor_proposal_conversation_owner",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_advisor_proposal_id_user"),
        sa.CheckConstraint(
            "status IN ('draft','applied','rejected','undone','expired')",
            name="advisor_proposal_status_allowed",
        ),
    )
    op.create_index(
        "ix_advisor_proposals_user_status_created",
        "advisor_proposals",
        ["user_id", "status", "created_at"],
    )

    op.create_table(
        "advisor_proposal_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(48), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(180), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=False),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["proposal_id", "user_id"],
            ["advisor_proposals.id", "advisor_proposals.user_id"],
            name="fk_advisor_proposal_action_owner",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "action_type IN ('budget_category_monthly_set','goal_monthly_contribution_set',"
            "'debt_extra_payment_set','debt_strategy_set','forecast_reserve_set')",
            name="advisor_proposal_action_type_allowed",
        ),
        sa.UniqueConstraint("proposal_id", "sort_order", name="uq_advisor_proposal_action_order"),
    )
    op.create_index(
        "ix_advisor_proposal_actions_proposal",
        "advisor_proposal_actions",
        ["proposal_id", "sort_order"],
    )

    op.create_table(
        "advisor_proposal_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["proposal_id", "user_id"],
            ["advisor_proposals.id", "advisor_proposals.user_id"],
            name="fk_advisor_proposal_execution_owner",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("operation IN ('apply','undo')", name="advisor_proposal_execution_operation_allowed"),
        sa.CheckConstraint("outcome IN ('success','failure')", name="advisor_proposal_execution_outcome_allowed"),
    )
    op.create_index(
        "ix_advisor_proposal_executions_proposal_created",
        "advisor_proposal_executions",
        ["proposal_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_advisor_proposal_executions_proposal_created", table_name="advisor_proposal_executions")
    op.drop_table("advisor_proposal_executions")
    op.drop_index("ix_advisor_proposal_actions_proposal", table_name="advisor_proposal_actions")
    op.drop_table("advisor_proposal_actions")
    op.drop_index("ix_advisor_proposals_user_status_created", table_name="advisor_proposals")
    op.drop_table("advisor_proposals")
