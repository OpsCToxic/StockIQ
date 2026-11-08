"""Review queue for low-confidence entity matches.

`python -m stockiq.entities.review list` shows what is waiting. Decisions become aliases
(`source = 'review'`), which the resolver treats as curated, so the same mention resolves exactly
next time. Rejected items stay rejected (the queue is unique on source and source_ref).
"""

import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import Connection, text

from stockiq.entities.names import normalize_name
from stockiq.entities.resolver import Mention, Resolution

REVIEW_SOURCE = "review"


def enqueue(
    conn: Connection, source: str, source_ref: str, mention: Mention, result: Resolution
) -> None:
    """Queue a mention for review. A decided item is never reopened; a pending one is refreshed."""
    conn.execute(
        text(
            """
            INSERT INTO review_queue
                (source, source_ref, mention, candidates, proposed_entity_id, confidence, method)
            VALUES (:s, :r, CAST(:m AS jsonb), CAST(:c AS jsonb), :e, :conf, :method)
            ON CONFLICT (source, source_ref) DO UPDATE SET
                mention = EXCLUDED.mention, candidates = EXCLUDED.candidates,
                proposed_entity_id = EXCLUDED.proposed_entity_id,
                confidence = EXCLUDED.confidence, method = EXCLUDED.method
            WHERE review_queue.status = 'pending'
            """
        ),
        {
            "s": source,
            "r": source_ref,
            "m": json.dumps({k: v for k, v in asdict(mention).items() if v}),
            "c": json.dumps(
                [
                    {"entity_id": c.entity_id, "name": c.name, "score": str(c.score), "via": c.via}
                    for c in result.candidates
                ]
            ),
            "e": result.entity_id,
            "conf": result.confidence,
            "method": result.method,
        },
    )


def pending(conn: Connection, limit: int = 50) -> list[dict[str, object]]:
    rows = conn.execute(
        text(
            """
            SELECT q.id, q.source_ref, q.mention, q.candidates, q.confidence, q.method,
                   e.name AS proposed
            FROM review_queue q LEFT JOIN entity e ON e.id = q.proposed_entity_id
            WHERE q.status = 'pending' ORDER BY q.confidence DESC, q.id LIMIT :n
            """
        ),
        {"n": limit},
    ).all()
    return [dict(r._mapping) for r in rows]


def accept(conn: Connection, queue_id: int, entity_id: int) -> None:
    """The mention IS this entity. Record the name and any identifiers as curated aliases."""
    item = conn.execute(
        text("SELECT mention, status FROM review_queue WHERE id = :i"), {"i": queue_id}
    ).one_or_none()
    if item is None:
        raise ValueError(f"no review item {queue_id}")
    if item.status != "pending":
        raise ValueError(f"item {queue_id} is already {item.status}")
    if conn.execute(text("SELECT 1 FROM entity WHERE id = :i"), {"i": entity_id}).first() is None:
        raise ValueError(f"no entity {entity_id}")
    now = datetime.now(UTC)
    mention = item.mention
    aliases: list[tuple[str, str]] = []
    if mention.get("name") and normalize_name(mention["name"]):
        aliases.append(("name", normalize_name(mention["name"])))
    for kind in ("cusip", "isin", "figi"):
        if mention.get(kind):
            aliases.append((kind, mention[kind]))
    if mention.get("ticker"):
        aliases.append(("ticker", mention["ticker"].upper()))
    for kind, alias in aliases:
        # The curated alias replaces any open one with the same value: if the resolver had it
        # pointing at another entity, that was wrong, and a human just said so.
        conn.execute(
            text(
                "UPDATE entity_alias SET valid_to = :n WHERE kind = :k AND alias = :a "
                "AND valid_to IS NULL AND entity_id <> :e AND source <> 'sec_company_tickers'"
            ),
            {"n": now, "k": kind, "a": alias, "e": entity_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from, known_at)
                SELECT :e, :a, :k, :src, :n, :n
                WHERE NOT EXISTS (
                    SELECT 1 FROM entity_alias WHERE entity_id = :e AND alias = :a AND kind = :k
                      AND source = :src AND valid_to IS NULL)
                """
            ),
            {"e": entity_id, "a": alias, "k": kind, "src": REVIEW_SOURCE, "n": now},
        )
    conn.execute(
        text(
            "UPDATE review_queue SET status = 'accepted', decided_entity_id = :e, decided_at = :n "
            "WHERE id = :i"
        ),
        {"e": entity_id, "n": now, "i": queue_id},
    )


def reject(conn: Connection, queue_id: int) -> None:
    """None of the candidates is right; leave the mention unlinked and do not ask again."""
    done = conn.execute(
        text(
            "UPDATE review_queue SET status = 'rejected', decided_at = now() "
            "WHERE id = :i AND status = 'pending'"
        ),
        {"i": queue_id},
    ).rowcount
    if not done:
        raise ValueError(f"item {queue_id} is not pending")


def search(
    conn: Connection, query: str, limit: int = 8
) -> list[tuple[int, str, str | None, float]]:
    """Find entities by name to decide on a review item: (id, name, cik, similarity)."""
    norm = normalize_name(query)
    rows = conn.execute(
        text(
            """
            SELECT e.id, e.name, e.cik, max(similarity(a.alias, :n)) AS sim
            FROM entity_alias a JOIN entity e ON e.id = a.entity_id
            WHERE a.kind = 'name' AND a.valid_to IS NULL AND a.alias % :n
            GROUP BY e.id, e.name, e.cik ORDER BY sim DESC LIMIT :k
            """
        ),
        {"n": norm, "k": limit},
    ).all()
    return [(r.id, r.name, r.cik, float(r.sim)) for r in rows]


def _main(argv: list[str]) -> int:
    from stockiq.core.db import get_engine

    usage = (
        "usage: python -m stockiq.entities.review "
        "(list [N] | search TEXT | accept QUEUE_ID ENTITY_ID | reject QUEUE_ID)"
    )
    if not argv:
        print(usage)
        return 2
    with get_engine().begin() as conn:
        match argv:
            case ["list", *rest]:
                for item in pending(conn, int(rest[0]) if rest else 50):
                    print(f"#{item['id']}  {item['source_ref']}  {item['mention']}")
                    print(
                        f"     {item['method']} {item['confidence']}  proposed: {item['proposed']}"
                    )
                    for c in item["candidates"][:3]:  # type: ignore[index]
                        print(f"       candidate {c['entity_id']}: {c['name']} ({c['score']})")
            case ["search", *words] if words:
                for i, name, cik, sim in search(conn, " ".join(words)):
                    print(f"{i}\t{name}\tCIK {cik}\t{sim:.2f}")
            case ["accept", qid, eid]:
                accept(conn, int(qid), int(eid))
                print(f"accepted #{qid} as entity {eid}")
            case ["reject", qid]:
                reject(conn, int(qid))
                print(f"rejected #{qid}")
            case _:
                print(usage)
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
