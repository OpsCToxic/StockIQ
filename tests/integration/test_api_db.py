"""Needs `make up` and `make migrate`.

The API reads through the `get_conn` dependency, which these tests replace with a transaction that
is rolled back, so no test commits a row to the real database.
"""

from collections import defaultdict
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from stockiq.api.app import app
from stockiq.api.portfolio import get_conn
from stockiq.core.db import get_engine

pytestmark = pytest.mark.integration


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias, account, document, review_queue CASCADE"))
        app.dependency_overrides[get_conn] = lambda: c
        yield c
        app.dependency_overrides.clear()
        trans.rollback()


def _entity(conn: Connection, name: str, kind: str) -> int:
    return int(
        conn.execute(
            text("INSERT INTO entity (name, type) VALUES (:n, :t) RETURNING id"),
            {"n": name, "t": kind},
        ).scalar_one()
    )


def _edge(conn: Connection, src: int, dst: int, kind: str, weight: str, doc: int) -> int:
    edge = conn.execute(
        text(
            "INSERT INTO edge (src_id, dst_id, type, weight, valid_from, confidence, known_at) "
            "VALUES (:s, :d, :t, :w, '2026-03-31', 0.95, '2026-05-30') RETURNING id"
        ),
        {"s": src, "d": dst, "t": kind, "w": Decimal(weight)},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO edge_evidence (edge_id, doc_id, section, span_text, url) "
            "VALUES (:e, :d, 'invstOrSec', '<invstOrSec>x</invstOrSec>', 'https://sec.gov/x.xml')"
        ),
        {"e": edge, "d": doc},
    )
    return int(edge)


def _seed(conn: Connection) -> dict[str, int]:
    """$1,000 in leveraged fund LEV (20% STOCK-A, 10% STOCK-B, plus a 180% swap on STOCK-A),
    $500 directly in STOCK-A, $50 cash."""
    fund = _entity(conn, "LEV", "fund")
    a, b = _entity(conn, "STOCK-A", "company"), _entity(conn, "STOCK-B", "company")
    acct = conn.execute(
        text("INSERT INTO account (broker, name) VALUES ('t', 'a') RETURNING id")
    ).scalar_one()
    doc = conn.execute(
        text(
            "INSERT INTO document (source, source_id, kind, raw_uri, hash) "
            "VALUES ('nport', 'd', 'k', 's3://x', 'h') RETURNING id"
        )
    ).scalar_one()
    for sec, ticker, value in ((fund, "LEV", 1000), (a, "AAA", 500)):
        conn.execute(
            text(
                "INSERT INTO holding (account_id, security_id, as_of, qty, market_value, ticker, "
                "known_at) VALUES (:a, :s, '2026-06-01', 1, :v, :t, '2026-06-02')"
            ),
            {"a": acct, "s": sec, "v": value, "t": ticker},
        )
    conn.execute(
        text(
            "INSERT INTO cash_balance (account_id, as_of, amount, known_at) "
            "VALUES (:a, '2026-06-01', 50, '2026-06-02')"
        ),
        {"a": acct},
    )
    conn.execute(
        text(
            "INSERT INTO fund_holding (fund_id, as_of, known_at, doc_id, seq, name, asset_cat, "
            "payoff_profile, country, pct_val) "
            "VALUES (:f, '2026-03-31', '2026-05-30', :d, 0, 'x', 'EC', 'Long', 'US', 30)"
        ),
        {"f": fund, "d": doc},
    )
    e1 = _edge(conn, fund, a, "CONTAINS", "0.2", doc)
    _edge(conn, fund, b, "CONTAINS", "0.1", doc)
    e3 = _edge(conn, fund, a, "SYNTHETIC", "1.8", doc)
    return {"fund": fund, "a": a, "b": b, "contains_a": e1, "swap_a": e3}


def _get(path: str, **params: Any) -> Any:
    return TestClient(app).get(path, params=params)


def test_exposure_reconciles_and_the_sankey_conserves_value(conn: Connection) -> None:
    _seed(conn)
    r = _get("/portfolio/exposure", as_of="2026-07-01T00:00:00Z", top=15)
    assert r.status_code == 200
    body = r.json()
    assert body["reconciles"] is True
    assert Decimal(body["total_value"]) == Decimal(1550)
    links = body["sankey"]["links"]
    out_of_portfolio = sum(Decimal(x["value"]) for x in links if x["source"] == "portfolio")
    assert out_of_portfolio == Decimal(1550)  # holdings plus cash
    into: dict[str, Decimal] = defaultdict(Decimal)
    out: dict[str, Decimal] = defaultdict(Decimal)
    for x in links:
        into[x["target"]] += Decimal(x["value"])
        out[x["source"]] += Decimal(x["value"])
    for node in body["sankey"]["nodes"]:
        if node["kind"] == "holding":
            assert into[node["id"]] == out[node["id"]], node  # nothing appears or vanishes


def test_swap_exposure_is_kept_out_of_the_funded_flows(conn: Connection) -> None:
    ids = _seed(conn)
    body = _get("/portfolio/exposure", as_of="2026-07-01T00:00:00Z").json()
    assert all(x["kind"] != "swap" for x in body["sankey"]["links"])
    (swap,) = body["sankey"]["swap_links"]
    assert Decimal(swap["value"]) == Decimal(1800) and swap["edge_id"] == ids["swap_a"]
    econ = {x["name"]: Decimal(x["share"]) for x in body["economic_companies"]}
    assert econ["STOCK-A"] > 1  # more than 100% of the money, because of the swap
    assert any(f["basis"] == "economic" and f["name"] == "STOCK-A" for f in body["flags"])


def test_top_folds_the_rest_into_one_node_without_losing_value(conn: Connection) -> None:
    _seed(conn)
    body = _get("/portfolio/exposure", as_of="2026-07-01T00:00:00Z", top=1).json()
    assert "other" in {n["kind"] for n in body["sankey"]["nodes"]}
    links = body["sankey"]["links"]
    to_companies = sum(
        Decimal(x["value"]) for x in links if x["target"].startswith("c:") or x["target"] == "other"
    )
    unlooked = sum(Decimal(x["value"]) for x in links if x["target"] == "unlooked")
    assert to_companies + unlooked + Decimal(body["cash"]) == Decimal(1550)


def test_evidence_endpoint_returns_the_filed_text_and_url(conn: Connection) -> None:
    ids = _seed(conn)
    r = _get(f"/edges/{ids['contains_a']}/evidence")
    assert r.status_code == 200
    body = r.json()
    assert (body["from_entity"], body["to_entity"], body["edge_type"]) == (
        "LEV",
        "STOCK-A",
        "CONTAINS",
    )
    assert body["total"] == 1 and body["evidence"][0]["span_text"].startswith("<invstOrSec>")
    assert body["evidence"][0]["url"] == "https://sec.gov/x.xml"


def test_unknown_edge_and_empty_portfolio_are_404(conn: Connection) -> None:
    assert _get("/edges/999999/evidence").status_code == 404
    assert _get("/portfolio/exposure").status_code == 404  # nothing seeded: no snapshot


def test_a_date_before_the_snapshot_was_known_is_404(conn: Connection) -> None:
    _seed(conn)
    assert _get("/portfolio/exposure", as_of="2026-05-01T00:00:00Z").status_code == 404


def test_health_and_openapi_are_served() -> None:
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    paths = client.get("/openapi.json").json()["paths"]
    assert "/portfolio/exposure" in paths and "/edges/{edge_id}/evidence" in paths
