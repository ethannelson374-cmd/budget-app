"""Add shared budget memberships, subscription tracking, and TOTP replay state.

Revision ID: 20260820_0023
Revises: 20260817_0022
Create Date: 2026-08-20
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0023"
down_revision: str | None = "20260817_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_sqlite_foreign_keys(enabled: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    with op.get_context().autocommit_block():
        bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "budget_memberships",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("budget_owner_user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('owner','member')", name="budget_membership_role_allowed"),
        sa.ForeignKeyConstraint(["budget_owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_budget_memberships_owner",
        "budget_memberships",
        ["budget_owner_user_id", "user_id"],
        unique=False,
    )
    # Every existing account starts as the owner of its own financial space.
    if bind.dialect.name == "mysql":
        bind.execute(
            sa.text(
                "INSERT INTO budget_memberships (user_id, budget_owner_user_id, role, joined_at) "
                "SELECT id, id, 'owner', UTC_TIMESTAMP() FROM users"
            )
        )
    else:
        bind.execute(
            sa.text(
                "INSERT INTO budget_memberships (user_id, budget_owner_user_id, role, joined_at) "
                "SELECT id, id, 'owner', CURRENT_TIMESTAMP FROM users"
            )
        )

    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        _set_sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table("user_invitations") as batch:
            batch.add_column(
                sa.Column("invite_type", sa.String(length=16), nullable=False, server_default="independent")
            )
            batch.add_column(sa.Column("budget_owner_user_id", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("accepted_user_id", sa.Integer(), nullable=True))
            batch.create_check_constraint(
                "user_invitation_type_allowed",
                "invite_type IN ('independent','shared')",
            )
            batch.create_foreign_key(
                "fk_user_invitation_budget_owner",
                "users",
                ["budget_owner_user_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch.create_foreign_key(
                "fk_user_invitation_accepted_user",
                "users",
                ["accepted_user_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index(
                "ix_user_invitations_budget_owner",
                ["budget_owner_user_id", "created_at"],
                unique=False,
            )
    finally:
        if sqlite:
            _set_sqlite_foreign_keys(True)

    with op.batch_alter_table("user_totp") as batch:
        batch.add_column(sa.Column("last_used_counter", sa.Integer(), nullable=True))

    with op.batch_alter_table("recurring_streams") as batch:
        batch.add_column(
            sa.Column("subscription_detected", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("subscription_override", sa.Boolean(), nullable=True))
        batch.add_column(
            sa.Column("subscription_status", sa.String(length=16), nullable=False, server_default="active")
        )
        batch.create_check_constraint(
            "recurring_stream_subscription_status_allowed",
            "subscription_status IN ('active','paused','cancelled')",
        )
        batch.create_index(
            "ix_recurring_streams_user_subscription",
            ["user_id", "subscription_status", "next_expected_date"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("recurring_streams") as batch:
        batch.drop_index("ix_recurring_streams_user_subscription")
        batch.drop_constraint("recurring_stream_subscription_status_allowed", type_="check")
        batch.drop_column("subscription_status")
        batch.drop_column("subscription_override")
        batch.drop_column("subscription_detected")

    with op.batch_alter_table("user_totp") as batch:
        batch.drop_column("last_used_counter")

    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        _set_sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table("user_invitations") as batch:
            batch.drop_index("ix_user_invitations_budget_owner")
            batch.drop_constraint("fk_user_invitation_accepted_user", type_="foreignkey")
            batch.drop_constraint("fk_user_invitation_budget_owner", type_="foreignkey")
            batch.drop_constraint("user_invitation_type_allowed", type_="check")
            batch.drop_column("accepted_user_id")
            batch.drop_column("budget_owner_user_id")
            batch.drop_column("invite_type")
    finally:
        if sqlite:
            _set_sqlite_foreign_keys(True)

    op.drop_index("ix_budget_memberships_owner", table_name="budget_memberships")
    op.drop_table("budget_memberships")
