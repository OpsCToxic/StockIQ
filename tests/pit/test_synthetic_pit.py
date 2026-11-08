"""Swap-based exposure obeys the same known-time rules. Needs `make up` and `make migrate`."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Connection, text

from stockiq.core.db import get_engine
from stockiq.graph.exposure import look_through

pytestmark = [pytest.mark.integration, pytest.mark.pit]


def utc(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


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


def _leveraged_fund(conn: Connection, swap_known: datetime) -> tuple[int, int]:
    """$1,000 in a 2x-style fund: 20% direct stock, 180% swaps, filed at `swap_known`."""
    fund, stock = _entity(conn, "LEV", "fund"), _entity(conn, "STOCKCO", "company")
    acct = conn.execute(
        text("INSERT INTO account (broker, name) VALUES ('t', 'a') RETURNING id")
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO holding (account_id, security_id, as_of, qty, market_value, known_at) "
            "VALUES (:a, :s, '2026-06-01', 1, 1000, '2026-06-02')"
        ),
        {"a": acct, "s": fund},
    )
    doc = conn.execute(
        text(
            "INSERT INTO document (source, source_id, kind, raw_uri, hash) "
            "VALUES ('t', 'd', 'k', 's3://x', 'h') RETURNING id"
        )
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO fund_holding (fund_id, as_of, known_at, doc_id, seq, name, asset_cat, "
            "payoff_profile, country, pct_val, constituent_id) "
            "VALUES (:f, '2026-03-31', :k, :d, 0, 'x', 'EC', 'Long', 'US', 20, :c)"
        ),
        {"f": fund, "k": swap_known, "d": doc, "c": stock},
    )
    for etype, weight in (("CONTAINS", "0.2"), ("SYNTHETIC", "1.8")):
        edge = conn.execute(
            text(
                "INSERT INTO edge (src_id, dst_id, type, weight, valid_from, confidence, known_at) "
                "VALUES (:f, :c, :t, :w, '2026-03-31', 0.95, :k) RETURNING id"
            ),
            {"f": fund, "c": stock, "t": etype, "w": Decimal(weight), "k": swap_known},
        ).scalar_one()
        conn.execute(
            text("INSERT INTO edge_evidence (edge_id, doc_id, url) VALUES (:e, :d, 'u')"),
            {"e": edge, "d": doc},
        )
    return fund, stock


def test_economic_exposure_adds_swaps_without_breaking_the_reconciliation(
    conn: Connection,
) -> None:
    _leveraged_fund(conn, swap_known=utc(2026, 5, 30))
    x = look_through(conn, utc(2026, 7, 1))
    by_name = {x.names[i]: v for i, v in x.economic_by_company.items()}
    assert by_name["STOCKCO"] == Decimal(2000)  # 200% of the $1,000 held
    assert x.company_total == Decimal(200)  # funded value only
    assert x.synthetic_by_company and sum(x.synthetic_by_company.values()) == Decimal(1800)
    assert x.reconciles_to == x.total_value  # swaps are not money, so they are not in the sum


def test_swap_exposure_from_a_filing_not_yet_public_is_excluded(conn: Connection) -> None:
    _leveraged_fund(conn, swap_known=utc(2026, 8, 1))  # filed after as_of
    x = look_through(conn, utc(2026, 7, 1))
    assert not x.synthetic_by_company and not x.economic_by_company
    assert x.reconciles_to == x.total_value
