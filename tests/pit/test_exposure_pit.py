"""Look-through must only use facts known by `as_of`. Needs `make up` and `make migrate`."""

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


def _snapshot(
    conn: Connection, acct: int, secs: dict[int, int], cash: int, at: datetime, known: datetime
) -> None:
    for sec, value in secs.items():
        conn.execute(
            text(
                "INSERT INTO holding (account_id, security_id, as_of, qty, market_value, known_at) "
                "VALUES (:a, :s, :t, 1, :v, :k)"
            ),
            {"a": acct, "s": sec, "t": at, "v": value, "k": known},
        )
    conn.execute(
        text(
            "INSERT INTO cash_balance (account_id, as_of, amount, known_at) VALUES (:a, :t, :c, :k)"
        ),
        {"a": acct, "t": at, "c": cash, "k": known},
    )


def _portfolio(conn: Connection, snapshot_known: datetime) -> tuple[int, int, int, int]:
    """Account holding $1,000 of ETF FND and $500 of stock DIRECT, plus $50 cash."""
    fund, direct = _entity(conn, "FND", "fund"), _entity(conn, "DIRECT", "company")
    acct = int(
        conn.execute(
            text("INSERT INTO account (broker, name) VALUES ('t', 'a') RETURNING id")
        ).scalar_one()
    )
    _snapshot(conn, acct, {fund: 1000, direct: 500}, 50, utc(2026, 6, 1), snapshot_known)
    return acct, fund, direct, _entity(conn, "ACME", "company")


def _report(
    conn: Connection,
    fund: int,
    company: int,
    weight: str,
    valid_from: datetime,
    known: datetime,
    country: str = "US",
) -> None:
    """One filing version: a fund_holding line and the CONTAINS edge with its evidence."""
    doc = conn.execute(
        text(
            "INSERT INTO document (source, source_id, kind, raw_uri, hash) "
            "VALUES ('t', gen_random_uuid()::text, 'k', 's3://x', 'h') RETURNING id"
        )
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO fund_holding (fund_id, as_of, known_at, doc_id, seq, name, asset_cat, "
            "payoff_profile, country, pct_val, constituent_id) "
            "VALUES (:f, :d, :k, :doc, 0, 'x', 'EC', 'Long', :cty, :pct, :c)"
        ),
        {
            "f": fund,
            "d": valid_from.date(),
            "k": known,
            "doc": doc,
            "cty": country,
            "pct": Decimal(weight) * 100,
            "c": company,
        },
    )
    edge = conn.execute(
        text(
            "INSERT INTO edge (src_id, dst_id, type, weight, valid_from, confidence, known_at) "
            "VALUES (:f, :c, 'CONTAINS', :w, :vf, 1, :k) RETURNING id"
        ),
        {"f": fund, "c": company, "w": Decimal(weight), "vf": valid_from, "k": known},
    ).scalar_one()
    conn.execute(
        text("INSERT INTO edge_evidence (edge_id, doc_id, url) VALUES (:e, :d, 'u')"),
        {"e": edge, "d": doc},
    )


def _acme(conn: Connection, as_of: datetime) -> Decimal:
    return look_through(conn, as_of).company_values_by_name()["ACME"]


def test_parts_always_add_up_to_the_broker_total(conn: Connection) -> None:
    _, fund, _, acme = _portfolio(conn, utc(2026, 6, 2))
    _report(conn, fund, acme, "0.40", utc(2026, 3, 31), utc(2026, 5, 30))
    x = look_through(conn, utc(2026, 7, 1))
    assert x.total_value == Decimal(1550)
    assert x.reconciles_to == x.total_value
    assert x.country_total == x.total_value
    by_name = x.company_values_by_name()
    assert by_name["ACME"] == Decimal(400) and by_name["DIRECT"] == Decimal(500)


def test_snapshot_not_yet_known_is_excluded(conn: Connection) -> None:
    _portfolio(conn, snapshot_known=utc(2026, 7, 15))  # imported after as_of
    x = look_through(conn, utc(2026, 7, 1))
    assert not x.snapshot_as_of and x.total_value == 0


def test_fund_report_filed_after_as_of_is_not_used(conn: Connection) -> None:
    _, fund, _, acme = _portfolio(conn, utc(2026, 6, 2))
    # Report date is before as_of, but the filing only became public afterwards.
    _report(conn, fund, acme, "0.40", utc(2026, 3, 31), utc(2026, 8, 1))
    x = look_through(conn, utc(2026, 7, 1))
    assert "ACME" not in x.company_values_by_name()
    assert any("no fund holdings filing" in n.reason for n in x.not_looked_through)
    assert x.reconciles_to == x.total_value and x.country_total == x.total_value


def test_uses_the_report_that_was_latest_at_as_of_not_the_newest(conn: Connection) -> None:
    _, fund, _, acme = _portfolio(conn, utc(2026, 6, 2))
    _report(conn, fund, acme, "0.40", utc(2026, 3, 31), utc(2026, 5, 30))
    _report(conn, fund, acme, "0.90", utc(2026, 6, 30), utc(2026, 8, 29))  # known later
    assert _acme(conn, utc(2026, 7, 1)) == Decimal(400)
    assert _acme(conn, utc(2026, 9, 1)) == Decimal(900)


def test_edge_valid_to_set_by_a_later_unknown_report_is_ignored(conn: Connection) -> None:
    """valid_to embeds future knowledge; reading it would drop the fund before it was replaced."""
    _, fund, _, acme = _portfolio(conn, utc(2026, 6, 2))
    _report(conn, fund, acme, "0.40", utc(2026, 3, 31), utc(2026, 5, 30))
    conn.execute(text("UPDATE edge SET valid_to = '2026-06-30'"))  # a later report closed it
    assert _acme(conn, utc(2026, 7, 1)) == Decimal(400)


def test_amendment_is_a_new_version_known_only_from_its_own_filing(conn: Connection) -> None:
    _, fund, _, acme = _portfolio(conn, utc(2026, 6, 2))
    _report(conn, fund, acme, "0.40", utc(2026, 3, 31), utc(2026, 5, 30))
    _report(conn, fund, acme, "0.50", utc(2026, 3, 31), utc(2026, 6, 20))  # amended, same period
    before = look_through(conn, utc(2026, 6, 10))
    after = look_through(conn, utc(2026, 7, 1))
    assert before.company_values_by_name()["ACME"] == Decimal(400)
    assert after.company_values_by_name()["ACME"] == Decimal(500)
    # Both versions share a report date; countries must not add them together.
    assert before.country_total == before.total_value
    assert after.country_total == after.total_value


def test_a_later_cash_only_snapshot_replaces_old_positions(conn: Connection) -> None:
    acct, fund, _, acme = _portfolio(conn, utc(2026, 6, 2))
    _report(conn, fund, acme, "0.40", utc(2026, 3, 31), utc(2026, 5, 30))
    conn.execute(
        text(
            "INSERT INTO cash_balance (account_id, as_of, amount, known_at) "
            "VALUES (:a, '2026-06-10', 1550, '2026-06-11')"
        ),
        {"a": acct},
    )  # sold everything: no holding rows on that date
    x = look_through(conn, utc(2026, 7, 1))
    assert x.total_value == Decimal(1550) and x.company_total == 0 and x.cash == Decimal(1550)
    # ...but before that snapshot was known, the old positions still apply.
    assert look_through(conn, utc(2026, 6, 5)).company_total > 0


def test_weights_over_100_percent_are_labelled_not_hidden(conn: Connection) -> None:
    _, fund, _, acme = _portfolio(conn, utc(2026, 6, 2))
    _report(conn, fund, acme, "1.02", utc(2026, 3, 31), utc(2026, 5, 30))
    x = look_through(conn, utc(2026, 7, 1))
    rest = next(n for n in x.not_looked_through if n.label == "FND")
    assert rest.value < 0 and "more than 100%" in rest.reason
    assert x.reconciles_to == x.total_value
