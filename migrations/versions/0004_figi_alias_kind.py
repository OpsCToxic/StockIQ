"""Allow FIGI identifiers as entity aliases.

One company entity can have several FIGIs (one per share class), so FIGIs are stored as
`entity_alias` rows of kind 'figi' rather than in the single-valued `entity.figi` column.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE entity_alias DROP CONSTRAINT entity_alias_kind_check;
        ALTER TABLE entity_alias ADD CONSTRAINT entity_alias_kind_check
            CHECK (kind IN ('ticker', 'cusip', 'isin', 'figi', 'name', 'cashtag', 'review'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM entity_alias WHERE kind = 'figi';
        ALTER TABLE entity_alias DROP CONSTRAINT entity_alias_kind_check;
        ALTER TABLE entity_alias ADD CONSTRAINT entity_alias_kind_check
            CHECK (kind IN ('ticker', 'cusip', 'isin', 'name', 'cashtag', 'review'));
        """
    )
