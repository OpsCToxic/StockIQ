"""Needs `make up` and `make migrate`. Runs inside a transaction that is rolled back."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Connection, text

from stockiq.connectors.base import RawPayload, StoredPayload
from stockiq.connectors.massive.connector import (
    KIND_DIVIDENDS,
    KIND_GROUPED,
    KIND_SPLITS,
    MassiveActionsConnector,
    MassivePricesConnector,
)
from stockiq.core.db import get_engine

pytestmark = pytest.mark.integration

NY = ZoneInfo("America/New_York")
FIX = Path(__file__).parents[1] / "fixtures" / "massive"
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias, document CASCADE"))
        yield c
        trans.rollback()


def _entity(conn: Connection, name: str, tickers: list[str]) -> int:
    eid = conn.execute(
        text("INSERT INTO entity (name, type) VALUES (:n, 'company') RETURNING id"), {"n": name}
    ).scalar_one()
    for t in tickers:
        conn.execute(
            text(
                "INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from) "
                "VALUES (:e, :t, 'ticker', 'test', '2020-01-01')"
            ),
            {"e": eid, "t": t},
        )
    return int(eid)


def _doc(conn: Connection) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO document (source, source_id, kind, raw_uri, hash) "
                "VALUES ('massive', gen_random_uuid()::text, 'k', 's3://x', 'h') RETURNING id"
            )
        ).scalar_one()
    )


def _load_prices(conn: Connection) -> None:
    body = (FIX / "grouped_2026-11-06.json").read_bytes()
    raw = RawPayload("g", "json", body, NOW, kind=KIND_GROUPED)
    c = MassivePricesConnector(None, date(2026, 11, 2))
    c.upsert(conn, StoredPayload(raw, "s3://x", "h", _doc(conn)), c.parse(raw))


def _count(conn: Connection, sql: str) -> int:
    return int(conn.execute(text(sql)).scalar_one())


def test_two_share_classes_of_one_company_do_not_collide(conn: Connection) -> None:
    _entity(conn, "Alphabet", ["GOOG", "GOOGL"])
    _entity(conn, "Apple", ["AAPL"])
    _load_prices(conn)
    assert _count(conn, "SELECT count(*) FROM price_bar") == 3  # NOENTITY is skipped
    assert (
        _count(conn, "SELECT count(DISTINCT ticker) FROM price_bar WHERE ticker LIKE 'GOOG%'") == 2
    )


def test_price_load_is_idempotent_and_uses_the_close_as_known_time(conn: Connection) -> None:
    _entity(conn, "Apple", ["AAPL"])
    _load_prices(conn)
    _load_prices(conn)
    assert _count(conn, "SELECT count(*) FROM price_bar") == 1
    assert _count(conn, "SELECT count(*) FROM price_bar WHERE known_at = ts") == 1


def test_corporate_actions_load_once_and_skip_unknown_tickers(conn: Connection) -> None:
    aapl = _entity(conn, "Apple", ["AAPL"])
    for _ in range(2):
        for name, kind in (("dividends.json", KIND_DIVIDENDS), ("splits.json", KIND_SPLITS)):
            raw = RawPayload("a", "json", (FIX / name).read_bytes(), NOW, kind=kind)
            c = MassiveActionsConnector(None, date(2026, 1, 1))
            c.upsert(conn, StoredPayload(raw, "s3://x", "h", _doc(conn)), c.parse(raw))
    assert _count(conn, f"SELECT count(*) FROM corporate_action WHERE security_id = {aapl}") == 2
    kinds = conn.execute(text("SELECT kind FROM corporate_action ORDER BY kind")).scalars().all()
    assert kinds == ["dividend", "split"]
    known = conn.execute(
        text("SELECT known_at FROM corporate_action WHERE kind = 'dividend'")
    ).scalar_one()
    # Known from the midnight after the declaration date: it may have come out after the close.
    assert known.astimezone(NY).isoformat() == "2026-10-29T00:00:00-04:00"
