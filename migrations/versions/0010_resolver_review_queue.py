"""Entity resolver support: trigram index for fuzzy name matching, and the review queue.

Low-confidence matches never go straight into the graph as certain facts (invariant 6): they are
queued here with their candidates. A reviewer's decision becomes `entity_alias` rows
(source = 'review'), so the resolver improves from it.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
        CREATE INDEX entity_alias_name_trgm ON entity_alias
            USING gin (alias gin_trgm_ops) WHERE kind = 'name';

        CREATE TABLE review_queue (
            id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source             text        NOT NULL,
            source_ref         text        NOT NULL,
            mention            jsonb       NOT NULL,
            candidates         jsonb       NOT NULL DEFAULT '[]'::jsonb,
            proposed_entity_id bigint      REFERENCES entity (id),
            confidence         numeric     NOT NULL,
            method             text        NOT NULL,
            status             text        NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'accepted', 'rejected')),
            decided_entity_id  bigint      REFERENCES entity (id),
            decided_at         timestamptz,
            created_at         timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source, source_ref)
        );
        CREATE INDEX review_queue_pending ON review_queue (status, confidence DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE review_queue;
        DROP INDEX entity_alias_name_trgm;
        """
    )
