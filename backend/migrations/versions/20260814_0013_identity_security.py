"""Add private-family identity, recovery, sessions, and two-factor security.

Revision ID: 20260814_0013
Revises: 20260814_0012
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0013"
down_revision: str | None = "20260814_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_sqlite_foreign_keys(enabled: bool) -> None:
    """Protect child rows while SQLite batch-rebuilds the users table.

    SQLite implements ALTER operations such as changing nullability by copying
    the table, dropping the original, and renaming the copy. With foreign keys
    enabled, dropping ``users`` fires ON DELETE actions on every owner-scoped
    child table. Production MySQL does not use this rebuild path.
    """

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    with op.get_context().autocommit_block():
        bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        _set_sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table("users") as batch:
            batch.alter_column("password_hash", existing_type=sa.String(255), nullable=True)
            batch.add_column(sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
            batch.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    finally:
        if sqlite:
            _set_sqlite_foreign_keys(True)

    op.add_column("sessions", sa.Column("user_agent", sa.String(512), nullable=True))

    bind = op.get_bind()
    bind.execute(sa.text("UPDATE users SET email_verified_at = COALESCE(email_verified_at, created_at)"))
    owner_id = bind.execute(sa.text("SELECT MIN(id) FROM users")).scalar()
    if owner_id is not None:
        bind.execute(sa.text("UPDATE users SET is_admin = :is_admin WHERE id = :owner_id"), {"is_admin": True, "owner_id": owner_id})

    op.create_table(
        "auth_identities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("provider", "subject", name="uq_auth_identity_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_auth_identity_user_provider"),
    )
    op.create_index("ix_auth_identities_user", "auth_identities", ["user_id"])

    op.create_table(
        "user_invitations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("invited_by_user_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_invitations_email_status", "user_invitations", ["normalized_email", "expires_at"])
    op.create_index("ix_user_invitations_inviter", "user_invitations", ["invited_by_user_id", "created_at"])

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_password_reset_user_expires", "password_reset_tokens", ["user_id", "expires_at"])

    op.create_table(
        "oauth_states",
        sa.Column("state_digest", sa.String(64), primary_key=True),
        sa.Column("nonce_digest", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("invitation_id", sa.Integer(), nullable=True),
        sa.Column("return_to", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invitation_id"], ["user_invitations.id"], ondelete="CASCADE"),
        sa.CheckConstraint("purpose IN ('login','link')", name="oauth_state_purpose_allowed"),
    )
    op.create_index("ix_oauth_states_expires", "oauth_states", ["expires_at"])

    op.create_table(
        "two_factor_challenges",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_two_factor_challenges_expires", "two_factor_challenges", ["expires_at"])

    op.create_table(
        "user_totp",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("secret_nonce", sa.String(64), nullable=False),
        sa.Column("recovery_codes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("user_totp")
    op.drop_index("ix_two_factor_challenges_expires", table_name="two_factor_challenges")
    op.drop_table("two_factor_challenges")
    op.drop_index("ix_oauth_states_expires", table_name="oauth_states")
    op.drop_table("oauth_states")
    op.drop_index("ix_password_reset_user_expires", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_user_invitations_inviter", table_name="user_invitations")
    op.drop_index("ix_user_invitations_email_status", table_name="user_invitations")
    op.drop_table("user_invitations")
    op.drop_index("ix_auth_identities_user", table_name="auth_identities")
    op.drop_table("auth_identities")
    op.drop_column("sessions", "user_agent")
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        _set_sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("email_verified_at")
            batch.drop_column("is_admin")
            batch.alter_column("password_hash", existing_type=sa.String(255), nullable=False)
    finally:
        if sqlite:
            _set_sqlite_foreign_keys(True)
