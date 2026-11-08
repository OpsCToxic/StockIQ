"""Swap-based (synthetic) exposure for leveraged and derivative funds.

A 2x fund like TSLL holds most of its Tesla exposure through total-return swaps, which a look
through equity lines alone misses. `fund_report` stores net assets so a swap's notional can be
expressed as a fraction of the fund; SYNTHETIC edges carry that signed fraction with evidence.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE fund_report (
            doc_id       bigint PRIMARY KEY REFERENCES document (id),
            fund_id      bigint      NOT NULL REFERENCES entity (id),
            as_of        date        NOT NULL,
            known_at     timestamptz NOT NULL,
            net_assets   numeric,
            total_assets numeric
        );

        ALTER TABLE fund_holding ADD COLUMN swap_ref text;
        ALTER TABLE fund_holding ADD COLUMN notional numeric;
        ALTER TABLE fund_holding ADD COLUMN swap_direction text
            CHECK (swap_direction IN ('long', 'short'));

        ALTER TABLE edge DROP CONSTRAINT edge_type_check;
        ALTER TABLE edge ADD CONSTRAINT edge_type_check CHECK (type IN
            ('HOLDS', 'CONTAINS', 'SYNTHETIC', 'IN_SECTOR', 'INSIDER_OF', 'POSITION_IN'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM edge WHERE type = 'SYNTHETIC';
        ALTER TABLE edge DROP CONSTRAINT edge_type_check;
        ALTER TABLE edge ADD CONSTRAINT edge_type_check CHECK (type IN
            ('HOLDS', 'CONTAINS', 'IN_SECTOR', 'INSIDER_OF', 'POSITION_IN'));
        ALTER TABLE fund_holding DROP COLUMN swap_direction;
        ALTER TABLE fund_holding DROP COLUMN notional;
        ALTER TABLE fund_holding DROP COLUMN swap_ref;
        DROP TABLE fund_report;
        """
    )
