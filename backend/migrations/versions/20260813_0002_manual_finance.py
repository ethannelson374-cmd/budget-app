"""Add manual financial record sources for Phase 2A.

Revision ID: 20260813_0002
Revises: 20260812_0001
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0002"
down_revision: str | None = "20260812_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode keeps the migration compatible with the SQLite demo/test path
    # while emitting normal ALTER statements on MySQL HeatWave.
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("source_type", sa.String(12), nullable=False, server_default="manual")
        )
        batch_op.create_check_constraint(
            "account_source_type_allowed",
            "source_type IN ('manual','plaid')",
        )
        batch_op.create_index("ix_accounts_user_source", ["user_id", "source_type"])

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(
            sa.Column("source_type", sa.String(12), nullable=False, server_default="manual")
        )
        batch_op.create_check_constraint(
            "transaction_source_type_allowed",
            "source_type IN ('manual','plaid')",
        )
        batch_op.create_index(
            "ix_transactions_user_source_posted",
            ["user_id", "source_type", "posted_date"],
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_index("ix_transactions_user_source_posted")
        batch_op.drop_constraint("transaction_source_type_allowed", type_="check")
        batch_op.drop_column("source_type")

    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_index("ix_accounts_user_source")
        batch_op.drop_constraint("account_source_type_allowed", type_="check")
        batch_op.drop_column("source_type")
