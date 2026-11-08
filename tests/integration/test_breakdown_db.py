"""Needs `make up` and `make migrate`. Runs inside a transaction that is rolled back."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Connection, text

from stockiq.core.db import get_engine
from stockiq.graph.exposure import look_through

pytestmark = pytest.mark.integration

AS_OF = datetime(2026, 7, 1, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias, account, document CASCADE"))
        yield c
        trans.rollback()


def _entity(conn: Connection, name: str, kind: str) -> int:
    return int(
        conn.execute(
            text("INSERT INTO entity (name, type) VALUES (:n, :t) RETURNING id"),
            {"n": name, "t": kind},
        ).scalar_one()
    )


def _seed(conn: Connection) -> int:
    """$1,000 in a fund whose filing says: 20% matched stock, 5% unmatched stock, 130% money
    market, -60% swaps at fair value, and 5% not filed as lines (net other assets)."""
    fund, stock = _entity(conn, "LEV", "fund"), _entity(conn, "ACME", "company")
    acct = conn.execute(
        text("INSERT INTO account (broker, name) VALUES ('t', 'a') RETURNING id")
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO holding (account_id, security_id, as_of, qty, market_value, ticker, "
            "known_at) VALUES (:a, :s, '2026-06-01', 1, 1000, 'LEV', '2026-06-02')"
        ),
        {"a": acct, "s": fund},
    )
    doc = conn.execute(
        text(
            "INSERT INTO document (source, source_id, kind, raw_uri, hash) "
            "VALUES ('nport', 'd', 'k', 's3://x', 'h') RETURNING id"
        )
    ).scalar_one()
    lines = [
        ("EC", "Long", stock, 20),  # matched: becomes company exposure
        ("EC", "Long", None, 5),  # equity the filing reports but we could not match
        ("STIV", "Long", None, 130),
        ("DO", "N/A", None, -60),
    ]
    for seq, (cat, payoff, cid, pct) in enumerate(lines):
        conn.execute(
            text(
                "INSERT INTO fund_holding (fund_id, as_of, known_at, doc_id, seq, name, asset_cat, "
                "payoff_profile, country, pct_val, constituent_id) VALUES "
                "(:f, '2026-03-31', '2026-05-30', :d, :q, 'x', :c, :p, 'US', :pct, :cid)"
            ),
            {"f": fund, "d": doc, "q": seq, "c": cat, "p": payoff, "pct": pct, "cid": cid},
        )
    edge = conn.execute(
        text(
            "INSERT INTO edge (src_id, dst_id, type, weight, valid_from, confidence, known_at) "
            "VALUES (:f, :c, 'CONTAINS', 0.2, '2026-03-31', 1, '2026-05-30') RETURNING id"
        ),
        {"f": fund, "c": stock},
    ).scalar_one()
    conn.execute(
        text("INSERT INTO edge_evidence (edge_id, doc_id, url) VALUES (:e, :d, 'u')"),
        {"e": edge, "d": doc},
    )
    return int(fund)


def test_the_breakdown_adds_up_to_the_remainder_exactly(conn: Connection) -> None:
    _seed(conn)
    x = look_through(conn, AS_OF)
    remainder = sum((n.value for n in x.not_looked_through), Decimal(0))
    assert sum((p.value for p in x.breakdown), Decimal(0)) == remainder == Decimal(800)


def test_each_bucket_is_reported_at_its_filed_value(conn: Connection) -> None:
    _seed(conn)
    parts = {p.bucket: p for p in look_through(conn, AS_OF).breakdown}
    assert parts["cash"].value == Decimal(1300)  # more than the fund, because of the swaps
    assert parts["derivatives"].value == Decimal(-600)
    assert parts["unmatched_equity"].value == Decimal(50)
    # 100% - 20% matched stock = 80% remainder; lines cover 75%; 5% is net other assets.
    assert parts["other"].value == Decimal(50)
    assert parts["cash"].fund_share == Decimal("1.3") and parts["cash"].lines == 1


def test_only_unmatched_equity_counts_as_the_gap(conn: Connection) -> None:
    _seed(conn)
    assert look_through(conn, AS_OF).unmatched_equity_total == Decimal(50)


def test_a_fund_with_no_filing_known_is_one_unknown_part(conn: Connection) -> None:
    _seed(conn)
    x = look_through(conn, datetime(2026, 5, 1, tzinfo=UTC))  # before the filing was public
    # the snapshot was not known yet either, so nothing is shown at all
    assert x.breakdown == []
    conn.execute(
        text("UPDATE fund_holding SET known_at = '2026-08-01'"),
    )
    x = look_through(conn, AS_OF)
    assert [p.bucket for p in x.breakdown] == ["unknown"]
    assert sum((p.value for p in x.breakdown), Decimal(0)) == Decimal(1000)


def test_each_part_lists_its_filed_lines_with_your_share(conn: Connection) -> None:
    _seed(conn)
    parts = {p.bucket: p for p in look_through(conn, AS_OF).breakdown}
    (money_market,) = parts["cash"].items
    assert money_market.your_value == Decimal(1300)  # 130% of a $1,000 holding
    assert money_market.fund_share == Decimal("1.3")
    (swap,) = parts["derivatives"].items
    assert swap.your_value == Decimal(-600)
    # the netted remainder has no filed line of its own
    assert parts["other"].items == []
