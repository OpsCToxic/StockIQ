"""Ticker aliases from the first SEC seed have an unknown start, not a start on the seed date.

The SEC ticker files carry no history. The first seed's aliases were dated to the fetch time, so
the resolver, which respects validity windows, could not resolve any document older than that day.
Date them from the epoch instead: "start unknown, assumed unchanged since before our records".
That is an assumption, and wrong for a ticker that changed hands before the seed (ADR 0006); aliases
opened by later seeds keep their real start, so changes from here on are tracked properly.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE entity_alias SET valid_from = '1970-01-01T00:00:00Z'
        WHERE source = 'sec_company_tickers' AND kind = 'ticker'
          AND valid_from = (
            SELECT min(valid_from) FROM entity_alias
            WHERE source = 'sec_company_tickers' AND kind = 'ticker')
        """
    )


def downgrade() -> None:
    # The original seed time is not recoverable from the row; known_at still holds it.
    op.execute(
        """
        UPDATE entity_alias SET valid_from = known_at
        WHERE source = 'sec_company_tickers' AND kind = 'ticker'
          AND valid_from = '1970-01-01T00:00:00Z'
        """
    )
