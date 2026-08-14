"""Add Ask Budget advisor preferences and conversation history.

Revision ID: 20260813_0009
Revises: 20260813_0008
Create Date: 2026-08-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0009"
down_revision: str | None = "20260813_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_settings", sa.Column("advisor_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("user_settings", sa.Column("advisor_share_merchants", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user_settings", sa.Column("advisor_include_descriptions", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user_settings", sa.Column("advisor_store_history", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "advisor_conversations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", "user_id", name="uq_advisor_conversation_id_user"),
    )
    op.create_index("ix_advisor_conversations_user_updated", "advisor_conversations", ["user_id", "updated_at"])

    op.create_table(
        "advisor_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("context_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["advisor_conversations.id", "advisor_conversations.user_id"],
            name="fk_advisor_message_conversation_owner",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("role IN ('user','assistant')", name="advisor_message_role_allowed"),
    )
    op.create_index("ix_advisor_messages_conversation_created", "advisor_messages", ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_advisor_messages_conversation_created", table_name="advisor_messages")
    op.drop_table("advisor_messages")
    op.drop_index("ix_advisor_conversations_user_updated", table_name="advisor_conversations")
    op.drop_table("advisor_conversations")
    op.drop_column("user_settings", "advisor_store_history")
    op.drop_column("user_settings", "advisor_include_descriptions")
    op.drop_column("user_settings", "advisor_share_merchants")
    op.drop_column("user_settings", "advisor_enabled")
