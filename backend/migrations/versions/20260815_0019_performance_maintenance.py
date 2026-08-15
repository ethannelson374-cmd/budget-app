"""Add maintenance-oriented indexes and stable transaction paging.

Revision ID: 20260815_0019
Revises: 20260815_0018
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260815_0019"
down_revision: str | None = "20260815_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Most transaction screens sort by (posted_date, id). Keep the familiar index
    # name while extending it with the deterministic tie-breaker used by the API.
    op.drop_index("ix_transactions_user_posted", table_name="transactions")
    op.create_index(
        "ix_transactions_user_posted",
        "transactions",
        ["user_id", "posted_date", "id"],
        unique=False,
    )

    # Daily housekeeping scans these columns globally instead of by owner.
    op.create_index("ix_sessions_revoked", "sessions", ["revoked_at"], unique=False)
    op.create_index(
        "ix_user_invitations_expires", "user_invitations", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_password_reset_expires", "password_reset_tokens", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_login_throttles_updated", "login_throttles", ["updated_at"], unique=False
    )
    op.create_index(
        "ix_report_exports_created", "report_exports", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_report_exports_created", table_name="report_exports")
    op.drop_index("ix_login_throttles_updated", table_name="login_throttles")
    op.drop_index("ix_password_reset_expires", table_name="password_reset_tokens")
    op.drop_index("ix_user_invitations_expires", table_name="user_invitations")
    op.drop_index("ix_sessions_revoked", table_name="sessions")

    op.drop_index("ix_transactions_user_posted", table_name="transactions")
    op.create_index(
        "ix_transactions_user_posted",
        "transactions",
        ["user_id", "posted_date"],
        unique=False,
    )
