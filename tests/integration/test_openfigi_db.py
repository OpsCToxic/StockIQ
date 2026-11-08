"""Needs `make up` and `make migrate`. Runs inside a transaction that is rolled back."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from stockiq.connectors.base import RawPayload, StoredPayload
from stockiq.connectors.openfigi.connector import OpenFigiConnector
from stockiq.core.db import get_engine

pytestmark = pytest.mark.integration

FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "openfigi" / "mapping_aapl_googl_voo_brkb_unknown.json"
)
NOW = datetime(2026, 11, 8, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias CASCADE"))
        yield c
        trans.rollback()


def _entity_with_ticker(conn: Connection, name: str, ticker: str) -> int:
    eid = conn.execute(
        text("INSERT INTO entity (name, type) VALUES (:n, 'company') RETURNING id"), {"n": name}
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from) "
            "VALUES (:e, :t, 'ticker', 'test', :at)"
        ),
        {"e": eid, "t": ticker, "at": datetime(2020, 1, 1, tzinfo=UTC)},
    )
    return int(eid)


def _run(conn: Connection) -> OpenFigiConnector:
    raw = RawPayload("figi-x", "json", FIXTURE.read_bytes(), NOW, kind="openfigi_mapping")
    connector = OpenFigiConnector(client=None, tickers=[])
    connector.upsert(conn, StoredPayload(raw, "s3://x", "h", 0), connector.parse(raw))
    return connector


def test_figi_attaches_to_entity_and_is_idempotent(conn: Connection) -> None:
    aapl = _entity_with_ticker(conn, "Apple Inc.", "AAPL")
    _run(conn)
    _run(conn)
    figis = (
        conn.execute(
            text("SELECT alias FROM entity_alias WHERE entity_id = :e AND kind = 'figi'"),
            {"e": aapl},
        )
        .scalars()
        .all()
    )
    assert figis == ["BBG000B9XRY4"]


def test_ticker_with_no_entity_is_reported_not_linked(conn: Connection) -> None:
    connector = _run(conn)  # no entities seeded at all
    assert any(u.startswith("AAPL") for u in connector.unlinked)
    assert (
        conn.execute(text("SELECT count(*) FROM entity_alias WHERE kind = 'figi'")).scalar_one()
        == 0
    )
