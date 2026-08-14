"""Add saved reports and reproducible report export history.

Revision ID: 20260814_0012
Revises: 20260814_0011
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from alembic import op

revision: str = "20260814_0012"
down_revision: str | None = "20260814_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("range_key", sa.String(8), nullable=False),
        sa.Column("sections_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", "user_id", name="uq_saved_report_id_user"),
        sa.UniqueConstraint("user_id", "name", name="uq_saved_report_user_name"),
        sa.CheckConstraint("range_key IN ('30d','3m','6m','ytd','1y')", name="saved_report_range_allowed"),
    )
    op.create_index("ix_saved_reports_user_updated", "saved_reports", ["user_id", "updated_at"])

    op.create_table(
        "report_exports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("saved_report_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("range_key", sa.String(8), nullable=False),
        sa.Column("sections_json", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("content_blob", sa.LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql"), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["saved_report_id"], ["saved_reports.id"], ondelete="SET NULL"),
        sa.CheckConstraint("format IN ('csv','pdf')", name="report_export_format_allowed"),
        sa.CheckConstraint("range_key IN ('30d','3m','6m','ytd','1y')", name="report_export_range_allowed"),
    )
    op.create_index("ix_report_exports_user_created", "report_exports", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_report_exports_user_created", table_name="report_exports")
    op.drop_table("report_exports")
    op.drop_index("ix_saved_reports_user_updated", table_name="saved_reports")
    op.drop_table("saved_reports")
