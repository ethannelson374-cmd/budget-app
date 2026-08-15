"""Add user notification preferences and notification inbox.

Revision ID: 20260815_0016
Revises: 20260814_0015
Create Date: 2026-08-15
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0016"
down_revision: str | None = "20260814_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_notification_preferences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("spending_alerts", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("forecast_alerts", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("goal_milestones", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("recurring_changes", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("large_transaction_alerts", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("large_transaction_threshold", sa.Numeric(19, 4), nullable=False, server_default="250.0000"),
        sa.Column("weekly_summary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("monthly_summary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_notification_preferences_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_notification_preferences")),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("notification_type", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("action_route", sa.String(length=160), nullable=True),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_error", sa.String(length=160), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_notification_user_fingerprint"),
        sa.CheckConstraint("severity IN ('info','opportunity','important','critical')", name="notification_severity_allowed"),
    )
    op.create_index("ix_notifications_user_occurred", "notifications", ["user_id", "occurred_at"], unique=False)
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at", "dismissed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_index("ix_notifications_user_occurred", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("user_notification_preferences")
