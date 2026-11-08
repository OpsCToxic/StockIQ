"""Sector exposure uses only classifications known by as_of. Needs `make up`, `make migrate`."""

import gzip
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from stockiq.connectors.base import RawPayload, StoredPayload
from stockiq.connectors.sec_sic.connector import KIND, SecSicConnector
from stockiq.core.db import get_engine
from stockiq.graph.exposure import look_through

pytestmark = [pytest.mark.integration, pytest.mark.pit]

FIX = Path(__file__).parents[1] / "fixtures" / "sec_sic" / "submissions_aapl_trimmed.json"


def utc(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias, account, document CASCADE"))
        yield c
        trans.rollback()


def _apple(conn: Connection) -> int:
    apple = conn.execute(
        text(
            "INSERT INTO entity (name, type, cik) VALUES ('Apple Inc.', 'company', '0000320193') "
            "RETURNING id"
        )
    ).scalar_one()
    acct = conn.execute(
        text("INSERT INTO account (broker, name) VALUES ('t', 'a') RETURNING id")
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO holding (account_id, security_id, as_of, qty, market_value, known_at) "
            "VALUES (:a, :s, '2026-06-01', 1, 1000, '2026-06-02')"
        ),
        {"a": acct, "s": apple},
    )
    return int(apple)


def _classify(conn: Connection, body: bytes, at: datetime) -> None:
    raw = RawPayload("s", "json.gz", gzip.compress(body), at, kind=KIND, url="https://x/y.json")
    doc = conn.execute(
        text(
            "INSERT INTO document (source, source_id, kind, raw_uri, hash) "
            "VALUES ('sec_sic', gen_random_uuid()::text, 'k', 's3://x', 'h') RETURNING id"
        )
    ).scalar_one()
    c = SecSicConnector(None, [])
    c.upsert(conn, StoredPayload(raw, "s3://x", "h", doc), c.parse(raw))


def test_classification_is_unknown_before_it_was_fetched(conn: Connection) -> None:
    _apple(conn)
    _classify(conn, FIX.read_bytes(), utc(2026, 11, 8))
    before = look_through(conn, utc(2026, 7, 1))
    after = look_through(conn, utc(2026, 12, 1))
    assert before.by_sector == {"Unclassified": Decimal(1000)}
    assert after.by_sector == {"SIC 3571 Electronic Computers": Decimal(1000)}
    assert after.by_division == {"Manufacturing": Decimal(1000)}


def test_sector_totals_always_reconcile_to_the_portfolio(conn: Connection) -> None:
    _apple(conn)
    _classify(conn, FIX.read_bytes(), utc(2026, 6, 1))
    x = look_through(conn, utc(2026, 7, 1))
    assert sum(x.by_sector.values(), Decimal(0)) == x.total_value
    assert sum(x.by_division.values(), Decimal(0)) == x.total_value


def test_a_changed_sic_closes_the_old_edge_and_keeps_the_new_one_unbackdated(
    conn: Connection,
) -> None:
    _apple(conn)
    _classify(conn, FIX.read_bytes(), utc(2026, 6, 1))
    changed = FIX.read_text().replace(
        '"sic":"3571","sicDescription":"Electronic Computers"',
        '"sic":"7372","sicDescription":"Services-Prepackaged Software"',
    )
    _classify(conn, changed.encode(), utc(2026, 9, 1))
    assert look_through(conn, utc(2026, 7, 1)).by_division == {"Manufacturing": Decimal(1000)}
    assert look_through(conn, utc(2026, 10, 1)).by_division == {"Services": Decimal(1000)}
    open_edges = conn.execute(
        text("SELECT count(*) FROM edge WHERE type = 'IN_SECTOR' AND valid_to IS NULL")
    ).scalar_one()
    assert open_edges == 1
    assert (
        conn.execute(
            text(
                "SELECT count(*) FROM edge e WHERE type = 'IN_SECTOR' AND NOT EXISTS "
                "(SELECT 1 FROM edge_evidence v WHERE v.edge_id = e.id)"
            )
        ).scalar_one()
        == 0
    )


def test_reclassifying_the_same_sic_adds_nothing(conn: Connection) -> None:
    _apple(conn)
    _classify(conn, FIX.read_bytes(), utc(2026, 6, 1))
    _classify(conn, FIX.read_bytes(), utc(2026, 9, 1))
    assert (
        conn.execute(text("SELECT count(*) FROM edge WHERE type = 'IN_SECTOR'")).scalar_one() == 1
    )
