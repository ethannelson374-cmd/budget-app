"""Track Plaid environment and update-mode connection health.

Revision ID: 20260815_0017
Revises: 20260815_0016
Create Date: 2026-08-15
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0017"
down_revision: str | None = "20260815_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plaid_items") as batch:
        batch.add_column(sa.Column("environment", sa.String(length=16), nullable=False, server_default="sandbox"))
        batch.add_column(sa.Column("update_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("update_reason", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("last_webhook_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("plaid_item_environment_allowed", "environment IN ('sandbox','production')")
        batch.create_index("ix_plaid_items_user_environment", ["user_id", "environment"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("plaid_items") as batch:
        batch.drop_index("ix_plaid_items_user_environment")
        batch.drop_constraint("plaid_item_environment_allowed", type_="check")
        batch.drop_column("last_webhook_at")
        batch.drop_column("update_reason")
        batch.drop_column("update_required")
        batch.drop_column("environment")
