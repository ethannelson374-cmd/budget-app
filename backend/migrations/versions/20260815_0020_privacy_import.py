"""Add Phase 4 Stage 7 privacy controls.

Revision ID: 20260815_0020
Revises: 20260815_0019
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0020"
down_revision: str | None = "20260815_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.add_column(
            sa.Column(
                "advisor_share_planning_names",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("advisor_share_planning_names")
