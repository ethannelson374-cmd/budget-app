"""Add operational job heartbeats for reliability status.

Revision ID: 20260814_0014
Revises: 20260814_0013
Create Date: 2026-08-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0014"
down_revision: str | None = "20260814_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operational_jobs",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="never"),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.CheckConstraint(
            "status IN ('never','running','success','failed')",
            name=op.f("ck_operational_jobs_operational_job_status_allowed"),
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_operational_jobs")),
    )


def downgrade() -> None:
    op.drop_table("operational_jobs")
