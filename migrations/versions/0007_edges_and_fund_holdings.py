"""Graph edges with evidence, and parsed fund holdings (N-PORT).

Invariant 1: every edge has at least one `edge_evidence` row citing its source. `fund_holding`
keeps every reported line, resolved or not, so unresolved exposure stays visible instead of
vanishing. `known_at` is the public filing date, not the report date (invariant 2).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE edge (
            id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            src_id     bigint      NOT NULL REFERENCES entity (id),
            dst_id     bigint      NOT NULL REFERENCES entity (id),
            type       text        NOT NULL
                CHECK (type IN ('HOLDS', 'CONTAINS', 'IN_SECTOR', 'INSIDER_OF', 'POSITION_IN')),
            weight     numeric,
            valid_from timestamptz NOT NULL,
            valid_to   timestamptz,
            confidence numeric     NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
            known_at   timestamptz NOT NULL,
            UNIQUE (src_id, dst_id, type, valid_from),
            CHECK (valid_to IS NULL OR valid_to > valid_from)
        );
        CREATE INDEX edge_dst ON edge (dst_id, type);

        CREATE TABLE edge_evidence (
            id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            edge_id   bigint NOT NULL REFERENCES edge (id) ON DELETE CASCADE,
            doc_id    bigint NOT NULL REFERENCES document (id),
            section   text,
            span_text text,
            url       text   NOT NULL,
            UNIQUE (edge_id, doc_id, section, span_text)
        );

        CREATE TABLE fund_holding (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            fund_id          bigint      NOT NULL REFERENCES entity (id),
            as_of            date        NOT NULL,
            known_at         timestamptz NOT NULL,
            doc_id           bigint      NOT NULL REFERENCES document (id),
            seq              integer     NOT NULL,
            name             text        NOT NULL,
            title            text,
            cusip            text,
            isin             text,
            lei              text,
            asset_cat        text,
            payoff_profile   text,
            country          text,
            balance          numeric,
            val_usd          numeric,
            pct_val          numeric,
            constituent_id   bigint      REFERENCES entity (id),
            match_method     text,
            match_confidence numeric,
            UNIQUE (doc_id, seq)
        );
        CREATE INDEX fund_holding_fund ON fund_holding (fund_id, as_of);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE fund_holding;
        DROP TABLE edge_evidence;
        DROP TABLE edge;
        """
    )
