"""Corporate actions, share-class-safe prices, and broker-reported value on holdings.

Prices are stored unadjusted (ADR 0005). Adjusted series are computed from these rows, using only
actions with `known_at <= as_of`, so history never changes retroactively (invariant 2).

`entity` is one row per company, so a company with two listed share classes (GOOG/GOOGL) has two
price series. Price and corporate-action rows therefore carry the ticker, and `price_bar` is keyed
on (security_id, ticker, ts). `holding` keeps one row per entity; it records the ticker held and
the broker's market value at `as_of`, which the exposure reconciliation uses (ADR 0006).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE price_bar ALTER COLUMN v TYPE numeric;
        ALTER TABLE price_bar ADD COLUMN ticker text NOT NULL;
        ALTER TABLE price_bar DROP CONSTRAINT price_bar_pkey;
        ALTER TABLE price_bar ADD PRIMARY KEY (security_id, ticker, ts);

        ALTER TABLE holding ADD COLUMN ticker text;
        ALTER TABLE holding ADD COLUMN market_value numeric;

        CREATE TABLE corporate_action (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            security_id bigint      NOT NULL REFERENCES entity (id),
            ticker      text        NOT NULL,
            kind        text        NOT NULL CHECK (kind IN ('split', 'dividend')),
            ex_date     date        NOT NULL,
            split_from  numeric,
            split_to    numeric,
            cash_amount numeric,
            currency    text,
            declared_at date,
            pay_date    date,
            source      text        NOT NULL,
            source_id   text        NOT NULL,
            known_at    timestamptz NOT NULL,
            doc_id      bigint      REFERENCES document (id),
            UNIQUE (source, source_id),
            CHECK (kind <> 'split' OR (split_from > 0 AND split_to > 0)),
            CHECK (kind <> 'dividend' OR cash_amount IS NOT NULL)
        );
        CREATE INDEX corporate_action_lookup ON corporate_action (security_id, kind, ex_date);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE corporate_action;
        ALTER TABLE holding DROP COLUMN market_value;
        ALTER TABLE holding DROP COLUMN ticker;
        ALTER TABLE price_bar DROP CONSTRAINT price_bar_pkey;
        ALTER TABLE price_bar DROP COLUMN ticker;
        ALTER TABLE price_bar ADD PRIMARY KEY (security_id, ts);
        ALTER TABLE price_bar ALTER COLUMN v TYPE bigint USING round(v);
        """
    )
