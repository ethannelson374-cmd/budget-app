"""Treat Plaid provider identifiers as case-sensitive on MySQL.

Revision ID: 20260815_0018
Revises: 20260815_0017
Create Date: 2026-08-15

Plaid identifiers are opaque and case-sensitive. MySQL's normal utf8mb4
collations are commonly case-insensitive, which can collapse distinct Plaid
transaction IDs that differ only by letter case and cause false duplicate-key
errors during /transactions/sync.

SQLite already compares these identifiers case-sensitively for the application's
test/demo path, so this migration only changes MySQL/HeatWave column collations.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260815_0018"
down_revision: str | None = "20260815_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BINARY_ID = mysql.VARCHAR(length=255, collation="utf8mb4_bin")
_NORMAL_ID = mysql.VARCHAR(length=255)


def _alter(column: str, *, nullable: bool) -> None:
    op.alter_column(
        "transactions",
        column,
        existing_type=_NORMAL_ID,
        type_=_BINARY_ID,
        existing_nullable=nullable,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    _alter("external_id", nullable=True)
    _alter("pending_transaction_external_id", nullable=True)

    # These are also opaque Plaid identifiers. They have not caused the current
    # failure, but using the same exact-comparison semantics prevents the same
    # class of bug in Item/account lookups and uniqueness checks.
    op.alter_column(
        "plaid_items",
        "external_id",
        existing_type=_NORMAL_ID,
        type_=_BINARY_ID,
        existing_nullable=False,
    )
    op.alter_column(
        "accounts",
        "external_id",
        existing_type=_NORMAL_ID,
        type_=_BINARY_ID,
        existing_nullable=True,
    )
    op.alter_column(
        "financial_institutions",
        "external_id",
        existing_type=_NORMAL_ID,
        type_=_BINARY_ID,
        existing_nullable=True,
    )
