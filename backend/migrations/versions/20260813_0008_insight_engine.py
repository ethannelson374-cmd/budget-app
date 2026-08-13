"""Add deterministic financial insight history.

Revision ID: 20260813_0008
Revises: 20260813_0007
Create Date: 2026-08-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0008"
down_revision: str | None = "20260813_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "insight_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("action_route", sa.String(120), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_insight_user_fingerprint"),
        sa.CheckConstraint(
            "priority IN ('critical','important','opportunity','info')",
            name="insight_priority_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('active','dismissed','resolved')",
            name="insight_status_allowed",
        ),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="insight_score_range"),
    )
    op.create_index(
        "ix_insight_records_user_status_score",
        "insight_records",
        ["user_id", "status", "score"],
    )


def downgrade() -> None:
    op.drop_index("ix_insight_records_user_status_score", table_name="insight_records")
    op.drop_table("insight_records")
