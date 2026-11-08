"""Connector cursors, and fund identifiers on entity.

Funds share a filer (trust) CIK across many series, so a fund entity is keyed on its SEC series id
and keeps the trust CIK in `filer_cik` instead of the unique `cik` column.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE connector_cursor (
            source     text PRIMARY KEY,
            cursor     jsonb       NOT NULL DEFAULT '{}'::jsonb,
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        ALTER TABLE entity ADD COLUMN series_id text;
        ALTER TABLE entity ADD COLUMN filer_cik text;
        CREATE UNIQUE INDEX entity_series_id_key ON entity (series_id) WHERE series_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX entity_series_id_key;
        ALTER TABLE entity DROP COLUMN filer_cik;
        ALTER TABLE entity DROP COLUMN series_id;
        DROP TABLE connector_cursor;
        """
    )
