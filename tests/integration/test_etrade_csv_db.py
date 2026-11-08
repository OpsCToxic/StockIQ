"""Needs `make up` and `make migrate`. Runs inside a transaction that is rolled back."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from stockiq.connectors.base import RawPayload, StoredPayload
from stockiq.connectors.etrade_csv.connector import EtradeCsvConnector, parse_export
from stockiq.core.db import get_engine

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[1] / "fixtures" / "etrade_csv" / "PortfolioDownload.csv"


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias, account, document CASCADE"))
        yield c
        trans.rollback()


def _seed(conn: Connection, tickers: list[str]) -> None:
    for t in tickers:
        eid = conn.execute(
            text("INSERT INTO entity (name, type) VALUES (:n, 'company') RETURNING id"), {"n": t}
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from) "
                "VALUES (:e, :t, 'ticker', 'test', '2020-01-01')"
            ),
            {"e": eid, "t": t},
        )


def _import(conn: Connection) -> None:
    connector = EtradeCsvConnector(FIXTURE)
    (raw,), _ = asyncio.run(connector.fetch({}))
    doc_id = conn.execute(
        text(
            "INSERT INTO document (source, source_id, kind, raw_uri, hash) "
            "VALUES ('etrade_csv', :s, 'csv', 's3://x', 'h') "
            "ON CONFLICT (source, source_id) DO UPDATE SET hash = 'h' RETURNING id"
        ),
        {"s": raw.source_id},
    ).scalar_one()
    connector.upsert(conn, StoredPayload(raw, "s3://x", "h", doc_id), connector.parse(raw))


def _count(conn: Connection, table: str) -> int:
    return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())  # noqa: S608


def test_import_writes_holdings_and_cash_idempotently(conn: Connection) -> None:
    _seed(conn, ["AAPL", "MSFT", "VOO"])
    _import(conn)
    _import(conn)
    assert _count(conn, "holding") == 3
    assert _count(conn, "cash_balance") == 1
    assert _count(conn, "account") == 1
    msft = conn.execute(
        text(
            "SELECT h.qty, h.cost_basis FROM holding h JOIN entity e ON e.id = h.security_id "
            "WHERE e.name = 'MSFT'"
        )
    ).one()
    assert (msft.qty, msft.cost_basis) == (4, 1521)


def test_unresolved_symbol_aborts_the_import(conn: Connection) -> None:
    _seed(conn, ["AAPL", "MSFT"])  # VOO missing
    with pytest.raises(ValueError, match="VOO"):
        _import(conn)


def test_parse_matches_what_was_stored(conn: Connection) -> None:
    export = parse_export(FIXTURE.read_bytes())
    _seed(conn, ["AAPL", "MSFT", "VOO"])
    _import(conn)
    value = sum(p.value for p in export.positions) + export.cash
    assert value == export.total_value
    assert RawPayload  # imported for type parity with other tests
