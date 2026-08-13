"""Add Plaid transaction sync state and provider metadata for Phase 2C.

Revision ID: 20260813_0004
Revises: 20260813_0003
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0004"
down_revision: str | None = "20260813_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plaid_items") as batch_op:
        batch_op.add_column(sa.Column("transactions_cursor", sa.String(512), nullable=True))
        batch_op.add_column(
            sa.Column("transactions_update_status", sa.String(64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("transactions_last_synced_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("transactions_last_error_code", sa.String(80), nullable=True)
        )

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(
            sa.Column("pending_transaction_external_id", sa.String(255), nullable=True)
        )
        batch_op.add_column(sa.Column("original_description", sa.String(512), nullable=True))
        batch_op.add_column(sa.Column("payment_channel", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("pfc_primary", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("pfc_detailed", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("pfc_confidence", sa.String(24), nullable=True))

    op.create_index(
        "ix_transactions_user_external", "transactions", ["user_id", "external_id"]
    )
    op.create_index(
        "ix_transactions_user_pending_external",
        "transactions",
        ["user_id", "pending_transaction_external_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_user_pending_external", table_name="transactions")
    op.drop_index("ix_transactions_user_external", table_name="transactions")

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("pfc_confidence")
        batch_op.drop_column("pfc_detailed")
        batch_op.drop_column("pfc_primary")
        batch_op.drop_column("payment_channel")
        batch_op.drop_column("original_description")
        batch_op.drop_column("pending_transaction_external_id")

    with op.batch_alter_table("plaid_items") as batch_op:
        batch_op.drop_column("transactions_last_error_code")
        batch_op.drop_column("transactions_last_synced_at")
        batch_op.drop_column("transactions_update_status")
        batch_op.drop_column("transactions_cursor")
