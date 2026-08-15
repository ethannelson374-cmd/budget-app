"""Add per-user dashboard layout and onboarding preferences.

Revision ID: 20260814_0015
Revises: 20260814_0014
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0015"
down_revision: str | None = "20260814_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_dashboard_preferences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("layout_json", sa.Text(), nullable=False),
        sa.Column("preset", sa.String(length=24), nullable=False, server_default="everyday"),
        sa.Column("onboarding_dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_dashboard_preferences_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_dashboard_preferences")),
    )


def downgrade() -> None:
    op.drop_table("user_dashboard_preferences")
