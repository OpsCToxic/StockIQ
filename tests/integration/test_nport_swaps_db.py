"""Needs `make up` and `make migrate`. Runs inside a transaction that is rolled back."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from stockiq.connectors.base import RawPayload, StoredPayload
from stockiq.connectors.nport.connector import KIND_FILING, NportConnector, parse_report
from stockiq.core.db import get_engine

pytestmark = pytest.mark.integration

FIX = Path(__file__).parents[1] / "fixtures" / "nport"
URL = "https://www.sec.gov/Archives/edgar/data/1424958/x/primary_doc.xml"
KNOWN = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias, document CASCADE"))
        yield c
        trans.rollback()


def _seed(conn: Connection, with_tsla: bool = True) -> None:
    fund = conn.execute(
        text(
            "INSERT INTO entity (name, type, series_id, filer_cik) "
            "VALUES ('TSLL', 'fund', 'S000072483', '0001424958') RETURNING id"
        )
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from) "
            "VALUES (:f, 'TSLL', 'ticker', 'test', '2020-01-01')"
        ),
        {"f": fund},
    )
    if with_tsla:
        tesla = conn.execute(
            text("INSERT INTO entity (name, type) VALUES ('Tesla, Inc.', 'company') RETURNING id")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from) "
                "VALUES (:t, 'TSLA', 'ticker', 'test', '2020-01-01')"
            ),
            {"t": tesla},
        )


def _load(conn: Connection) -> None:
    body = (FIX / "nport_tsll.xml").read_bytes()
    raw = RawPayload("acc", "xml", body, KNOWN, url=URL, published_at=KNOWN, kind=KIND_FILING)
    doc = conn.execute(
        text(
            "INSERT INTO document (source, source_id, kind, raw_uri, hash, url) "
            "VALUES ('nport', gen_random_uuid()::text, 'nport_p', 's3://x', 'h', :u) RETURNING id"
        ),
        {"u": URL},
    ).scalar_one()
    c = NportConnector(None, [])
    c.upsert(conn, StoredPayload(raw, "s3://x", "h", doc), [parse_report(body, "acc", KNOWN)])


def test_swaps_become_one_synthetic_edge_with_seven_evidence_rows(conn: Connection) -> None:
    _seed(conn)
    _load(conn)
    edge = conn.execute(
        text(
            "SELECT e.weight, e.confidence, (SELECT count(*) FROM edge_evidence v "
            "WHERE v.edge_id = e.id AND v.span_text LIKE '%<swapDeriv%') AS n "
            "FROM edge e WHERE e.type = 'SYNTHETIC'"
        )
    ).one()
    # 5,591,981,553.15 notional over 3,034,816,690.84 net assets
    assert round(edge.weight, 4) == Decimal("1.8426")
    assert edge.confidence == Decimal("0.95")  # a ticker match, not an exact identifier
    assert edge.n == 7


def test_net_assets_are_stored_with_the_report(conn: Connection) -> None:
    _seed(conn)
    _load(conn)
    assert conn.execute(text("SELECT net_assets FROM fund_report")).scalar_one() == Decimal(
        "3034816690.840000000000"
    )


def test_swap_on_an_unknown_ticker_creates_no_edge_but_keeps_the_line(conn: Connection) -> None:
    _seed(conn, with_tsla=False)
    _load(conn)
    assert (
        conn.execute(text("SELECT count(*) FROM edge WHERE type = 'SYNTHETIC'")).scalar_one() == 0
    )
    kept = conn.execute(
        text("SELECT count(*) FROM fund_holding WHERE swap_ref = 'TSLA' AND constituent_id IS NULL")
    ).scalar_one()
    assert kept == 7


def test_reload_does_not_stack_synthetic_edges(conn: Connection) -> None:
    _seed(conn)
    _load(conn)
    first = conn.execute(text("SELECT count(*) FROM edge")).scalar_one()
    _load(conn)
    assert conn.execute(text("SELECT count(*) FROM edge")).scalar_one() == first


def test_reprocessing_a_filing_refreshes_the_swap_columns_not_just_the_match(
    conn: Connection,
) -> None:
    """Rows stored before the swap columns existed kept NULLs on every re-parse (a bug)."""
    _seed(conn)
    _load(conn)
    conn.execute(
        text("UPDATE fund_holding SET swap_ref = NULL, notional = NULL, counterparty = NULL")
    )
    _load(conn)
    row = conn.execute(
        text(
            "SELECT count(*) AS n, count(DISTINCT counterparty) AS cp, sum(notional) AS notional "
            "FROM fund_holding WHERE swap_ref = 'TSLA'"
        )
    ).one()
    assert (row.n, row.cp) == (7, 7)
    assert row.notional == Decimal("5591981553.15")
