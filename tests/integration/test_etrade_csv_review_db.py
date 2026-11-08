"""Needs `make up` and `make migrate`. Runs inside a transaction that is rolled back."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from stockiq.connectors.base import StoredPayload
from stockiq.connectors.etrade_csv.connector import EtradeCsvConnector
from stockiq.core.db import get_engine
from stockiq.entities import review

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[1] / "fixtures" / "etrade_csv" / "PortfolioDownload.csv"


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias, account, document, review_queue CASCADE"))
        yield c
        trans.rollback()


def _company_with_ticker(conn: Connection, name: str, ticker: str) -> int:
    eid = conn.execute(
        text("INSERT INTO entity (name, type) VALUES (:n, 'company') RETURNING id"), {"n": name}
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from) "
            "VALUES (:e, :t, 'ticker', 'test', '1970-01-01')"
        ),
        {"e": eid, "t": ticker},
    )
    return int(eid)


def _import(conn: Connection) -> EtradeCsvConnector:
    connector = EtradeCsvConnector(FIXTURE)
    (raw,), _ = asyncio.run(connector.fetch({}))
    doc_id = conn.execute(
        text(
            "INSERT INTO document (source, source_id, kind, raw_uri, hash) "
            "VALUES ('etrade_csv', gen_random_uuid()::text, 'csv', 's3://x', 'h') RETURNING id"
        )
    ).scalar_one()
    connector.upsert(conn, StoredPayload(raw, "s3://x", "h", doc_id), connector.parse(raw))
    return connector


def test_an_unmatched_symbol_aborts_and_is_reported_for_review(conn: Connection) -> None:
    _company_with_ticker(conn, "Apple Inc.", "AAPL")
    _company_with_ticker(conn, "Microsoft Corp", "MSFT")  # VOO is missing
    connector = EtradeCsvConnector(FIXTURE)
    with pytest.raises(ValueError, match="VOO") as e:
        (raw,), _ = asyncio.run(connector.fetch({}))
        connector.upsert(conn, StoredPayload(raw, "s3://x", "h", 0), connector.parse(raw))
    assert "review" in str(e.value)
    assert [m.ticker for m, _ in connector.unresolved] == ["VOO"]
    assert conn.execute(text("SELECT count(*) FROM holding")).scalar_one() == 0


def test_accepting_the_review_item_lets_the_same_file_import(conn: Connection) -> None:
    _company_with_ticker(conn, "Apple Inc.", "AAPL")
    _company_with_ticker(conn, "Microsoft Corp", "MSFT")
    voo = conn.execute(
        text(
            "INSERT INTO entity (name, type) VALUES ('Vanguard 500 Index Fund', 'fund') "
            "RETURNING id"
        )
    ).scalar_one()
    failed = EtradeCsvConnector(FIXTURE)
    (raw,), _ = asyncio.run(failed.fetch({}))
    with pytest.raises(ValueError):
        failed.upsert(conn, StoredPayload(raw, "s3://x", "h", 0), failed.parse(raw))
    for mention, result in failed.unresolved:
        review.enqueue(conn, "etrade_csv", f"symbol:{mention.ticker}", mention, result)
    (item,) = review.pending(conn)
    review.accept(conn, int(item["id"]), voo)  # type: ignore[arg-type]
    _import(conn)  # the same file now imports
    assert conn.execute(text("SELECT count(*) FROM holding")).scalar_one() == 3
