"""Phase 1 core tables: entity, entity_alias, document, account, holding, lot, price_bar.

Every table that feeds analytics carries event time and known time separately (invariant 2):
`as_of` / `ts` / `published_at` are event time; `known_at` is when StockIQ could have known it.
`price_bar` stores unadjusted prices only; splits and dividends arrive with the prices connector.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.execute(
        """
        CREATE TABLE entity (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name        text        NOT NULL,
            type        text        NOT NULL
                CHECK (type IN ('company', 'fund', 'sector', 'country', 'person', 'institution')),
            cik         text,
            figi        text,
            lei         text,
            public      boolean     NOT NULL DEFAULT true,
            sector_id   bigint      REFERENCES entity (id),
            country     text,
            known_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX entity_cik_key ON entity (cik) WHERE cik IS NOT NULL;
        CREATE UNIQUE INDEX entity_figi_key ON entity (figi) WHERE figi IS NOT NULL;
        CREATE UNIQUE INDEX entity_lei_key ON entity (lei) WHERE lei IS NOT NULL;

        CREATE TABLE entity_alias (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            entity_id   bigint      NOT NULL REFERENCES entity (id),
            alias       text        NOT NULL,
            kind        text        NOT NULL
                CHECK (kind IN ('ticker', 'cusip', 'isin', 'name', 'cashtag', 'review')),
            source      text        NOT NULL,
            valid_from  timestamptz NOT NULL,
            valid_to    timestamptz,
            known_at    timestamptz NOT NULL DEFAULT now(),
            CHECK (valid_to IS NULL OR valid_to > valid_from),
            UNIQUE (entity_id, alias, kind, valid_from)
        );
        CREATE INDEX entity_alias_lookup ON entity_alias (kind, lower(alias));

        CREATE TABLE document (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source       text        NOT NULL,
            source_id    text        NOT NULL,
            kind         text        NOT NULL,
            url          text,
            published_at timestamptz,
            ingested_at  timestamptz NOT NULL DEFAULT now(),
            raw_uri      text        NOT NULL,
            hash         text        NOT NULL,
            UNIQUE (source, source_id)
        );
        CREATE INDEX document_hash ON document (hash);

        CREATE TABLE account (
            id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            broker     text        NOT NULL,
            name       text        NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (broker, name)
        );

        CREATE TABLE holding (
            account_id  bigint      NOT NULL REFERENCES account (id),
            security_id bigint      NOT NULL REFERENCES entity (id),
            as_of       timestamptz NOT NULL,
            qty         numeric     NOT NULL,
            cost_basis  numeric,
            known_at    timestamptz NOT NULL DEFAULT now(),
            doc_id      bigint      REFERENCES document (id),
            PRIMARY KEY (account_id, security_id, as_of)
        );
        CREATE INDEX holding_known ON holding (account_id, known_at);

        CREATE TABLE lot (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            account_id  bigint      NOT NULL REFERENCES account (id),
            security_id bigint      NOT NULL REFERENCES entity (id),
            source_id   text        NOT NULL,
            acquired_at timestamptz NOT NULL,
            qty         numeric     NOT NULL,
            cost_basis  numeric,
            as_of       timestamptz NOT NULL,
            known_at    timestamptz NOT NULL DEFAULT now(),
            doc_id      bigint      REFERENCES document (id),
            UNIQUE (account_id, source_id, as_of)
        );

        CREATE TABLE price_bar (
            security_id bigint      NOT NULL REFERENCES entity (id),
            ts          timestamptz NOT NULL,
            o           numeric     NOT NULL,
            h           numeric     NOT NULL,
            l           numeric     NOT NULL,
            c           numeric     NOT NULL,
            v           bigint      NOT NULL,
            vwap        numeric,
            source      text        NOT NULL,
            known_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (security_id, ts)
        );
        """
    )
    op.execute(
        "SELECT create_hypertable('price_bar', 'ts', chunk_time_interval => INTERVAL '1 year')"
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE price_bar;
        DROP TABLE lot;
        DROP TABLE holding;
        DROP TABLE account;
        DROP TABLE document;
        DROP TABLE entity_alias;
        DROP TABLE entity;
        """
    )
