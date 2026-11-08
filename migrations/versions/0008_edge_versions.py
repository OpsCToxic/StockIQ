"""Edges are versioned by known_at, so an amended filing never rewrites what was known earlier.

An amended N-PORT for the same report date arrives later than the original. Keying edges on
`known_at` as well keeps both versions; look-through reads the latest version known by `as_of`.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE edge DROP CONSTRAINT edge_src_id_dst_id_type_valid_from_key;
        ALTER TABLE edge ADD CONSTRAINT edge_version_key
            UNIQUE (src_id, dst_id, type, valid_from, known_at);
        COMMENT ON COLUMN edge.valid_to IS
            'Set when a later report begins, so it embeds future knowledge. Never filter on it for '
            'point-in-time reads; use valid_from and known_at.';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE edge DROP CONSTRAINT edge_version_key;
        ALTER TABLE edge ADD CONSTRAINT edge_src_id_dst_id_type_valid_from_key
            UNIQUE (src_id, dst_id, type, valid_from);
        """
    )
