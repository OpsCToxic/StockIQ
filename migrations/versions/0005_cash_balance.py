"""Cash balances per account, so portfolio totals reconcile with the broker.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cash_balance (
            account_id bigint      NOT NULL REFERENCES account (id),
            as_of      timestamptz NOT NULL,
            amount     numeric     NOT NULL,
            known_at   timestamptz NOT NULL DEFAULT now(),
            doc_id     bigint      REFERENCES document (id),
            PRIMARY KEY (account_id, as_of)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE cash_balance")
