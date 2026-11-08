"""Swap counterparty on fund holdings, so each swap can be listed with who is on the other side.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE fund_holding ADD COLUMN counterparty text")


def downgrade() -> None:
    op.execute("ALTER TABLE fund_holding DROP COLUMN counterparty")
