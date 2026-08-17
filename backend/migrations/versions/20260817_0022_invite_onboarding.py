"""Replace email-bound invitations with link invitations and persist first-run progress.

Revision ID: 20260817_0022
Revises: 20260817_0021
Create Date: 2026-08-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0022"
down_revision: str | None = "20260817_0021"
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
    with op.batch_alter_table("user_settings") as batch:
        batch.add_column(sa.Column("onboarding_step", sa.Integer(), nullable=False, server_default="6"))

    # Existing accounts have already been using Budget and must never be forced
    # through the new out-of-box flow. New invite-created users are initialized
    # with onboarding_complete=false/onboarding_step=0 by application code.
    bind.execute(sa.text("UPDATE user_settings SET onboarding_complete = :complete, onboarding_step = 6"), {"complete": True})

    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        _set_sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table("user_invitations") as batch:
            batch.alter_column("email", existing_type=sa.String(320), nullable=True)
            batch.alter_column("normalized_email", existing_type=sa.String(320), nullable=True)
            batch.add_column(sa.Column("label", sa.String(120), nullable=True))
            batch.add_column(sa.Column("challenge_digest", sa.String(64), nullable=True))
            batch.add_column(sa.Column("challenge_expires_at", sa.DateTime(timezone=True), nullable=True))
            batch.create_unique_constraint("uq_user_invitations_challenge_digest", ["challenge_digest"])
    finally:
        if sqlite:
            _set_sqlite_foreign_keys(True)


def downgrade() -> None:
    bind = op.get_bind()
    # Link-only invitations cannot be represented by the old email-required
    # schema. Remove unredeemed link-only rows before restoring old nullability.
    bind.execute(sa.text("DELETE FROM user_invitations WHERE email IS NULL"))
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        _set_sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table("user_invitations") as batch:
            batch.drop_constraint("uq_user_invitations_challenge_digest", type_="unique")
            batch.drop_column("challenge_expires_at")
            batch.drop_column("challenge_digest")
            batch.drop_column("label")
            batch.alter_column("normalized_email", existing_type=sa.String(320), nullable=False)
            batch.alter_column("email", existing_type=sa.String(320), nullable=False)
    finally:
        if sqlite:
            _set_sqlite_foreign_keys(True)
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("onboarding_step")
