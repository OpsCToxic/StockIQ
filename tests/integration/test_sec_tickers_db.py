"""Needs `make up` and `make migrate`. Runs inside a transaction that is rolled back."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from stockiq.connectors.base import RawPayload, StoredPayload
from stockiq.connectors.sec_tickers.connector import KIND_COMPANY, KIND_FUND, SecTickersConnector
from stockiq.core.db import get_engine

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sec_tickers"
DAY1 = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        # Isolate from real seeded data: TRUNCATE is transactional in Postgres, so the rollback
        # below restores everything.
        c.execute(text("TRUNCATE entity, entity_alias CASCADE"))
        yield c
        trans.rollback()


def _load(
    conn: Connection, filename: str, kind: str, at: datetime, body: bytes | None = None
) -> None:
    raw = RawPayload(
        source_id=f"{kind}-{at:%Y-%m-%d}",
        ext="json",
        body=body if body is not None else (FIXTURES / filename).read_bytes(),
        fetched_at=at,
        kind=kind,
    )
    connector = SecTickersConnector(client=None)
    connector.upsert(conn, StoredPayload(raw, "s3://x", "h", 0), connector.parse(raw))


def _count(conn: Connection, sql: str) -> int:
    return int(conn.execute(text(sql)).scalar_one())


def test_seed_is_idempotent_and_groups_share_classes(conn: Connection) -> None:
    _load(conn, "company_tickers_exchange.json", KIND_COMPANY, DAY1)
    _load(conn, "company_tickers_exchange.json", KIND_COMPANY, DAY1 + timedelta(days=1))
    assert (
        _count(conn, "SELECT count(*) FROM entity WHERE type = 'company' AND cik = '0001652044'")
        == 1
    )
    assert (
        _count(
            conn,
            """SELECT count(*) FROM entity_alias a JOIN entity e ON e.id = a.entity_id
           WHERE e.cik = '0001652044' AND a.valid_to IS NULL""",
        )
        == 2
    )


def test_fund_series_with_two_classes_is_one_entity(conn: Connection) -> None:
    _load(conn, "company_tickers_mf.json", KIND_FUND, DAY1)
    assert _count(conn, "SELECT count(*) FROM entity WHERE series_id = 'S000002839'") == 1
    assert (
        _count(
            conn,
            """SELECT count(*) FROM entity_alias a JOIN entity e ON e.id = a.entity_id
           WHERE e.series_id = 'S000002839' AND a.alias = 'VOO' AND a.valid_to IS NULL""",
        )
        == 1
    )


def test_removed_ticker_alias_is_closed(conn: Connection) -> None:
    _load(conn, "company_tickers_exchange.json", KIND_COMPANY, DAY1)
    trimmed = (
        b'{"fields":["cik","name","ticker","exchange"],'
        b'"data":[[1652044,"Alphabet Inc.","GOOGL","Nasdaq"]]}'
    )
    _load(conn, "", KIND_COMPANY, DAY1 + timedelta(days=1), body=trimmed)
    closed = conn.execute(
        text(
            "SELECT valid_to FROM entity_alias "
            "WHERE alias = 'GOOG' AND source = 'sec_company_tickers'"
        )
    ).scalar_one()
    assert closed == DAY1 + timedelta(days=1)
