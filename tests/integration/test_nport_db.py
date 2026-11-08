"""Needs `make up` and `make migrate`. Runs inside a transaction that is rolled back."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from stockiq.connectors.base import RawPayload, StoredPayload
from stockiq.connectors.nport.connector import KIND_FILING, NportConnector, parse_report
from stockiq.core.db import get_engine

pytestmark = pytest.mark.integration

FIX = Path(__file__).parents[1] / "fixtures" / "nport"
URL = "https://www.sec.gov/Archives/edgar/data/36405/000003640526000473/primary_doc.xml"
KNOWN = datetime(2026, 8, 29, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias, document CASCADE"))
        yield c
        trans.rollback()


def _company(conn: Connection, name: str) -> int:
    return int(
        conn.execute(
            text("INSERT INTO entity (name, type) VALUES (:n, 'company') RETURNING id"), {"n": name}
        ).scalar_one()
    )


def _seed(conn: Connection) -> int:
    fund = conn.execute(
        text(
            "INSERT INTO entity (name, type, series_id, filer_cik) "
            "VALUES ('VOO', 'fund', 'S000002839', '0000036405') RETURNING id"
        )
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from) "
            "VALUES (:f, 'VOO', 'ticker', 'test', '2020-01-01')"
        ),
        {"f": fund},
    )
    for name in ("Apple Inc.", "Alphabet Inc.", "MICROSOFT CORP", "NVIDIA CORP"):
        _company(conn, name)
    return int(fund)


def _load(
    conn: Connection, known_at: datetime = KNOWN, accession: str = "0000036405-26-000473"
) -> None:
    body = (FIX / "nport_voo_trimmed.xml").read_bytes()
    raw = RawPayload(
        accession, "xml", body, known_at, url=URL, published_at=known_at, kind=KIND_FILING
    )
    doc = conn.execute(
        text(
            "INSERT INTO document (source, source_id, kind, raw_uri, hash, url) "
            "VALUES ('nport', :s, 'nport_p', 's3://x', 'h', :u) "
            "ON CONFLICT (source, source_id) DO UPDATE SET hash = 'h' RETURNING id"
        ),
        {"s": accession, "u": URL},
    ).scalar_one()
    c = NportConnector(None, [])
    c.upsert(
        conn, StoredPayload(raw, "s3://x", "h", doc), [parse_report(body, accession, known_at)]
    )


def _one(conn: Connection, sql: str) -> object:
    return conn.execute(text(sql)).scalar_one()


def test_resolves_by_name_aggregates_classes_and_cites_evidence(conn: Connection) -> None:
    _seed(conn)
    _load(conn)
    # 10 holdings stored; Apple, 2 x Alphabet, Microsoft, NVIDIA resolve; the rest do not.
    assert _one(conn, "SELECT count(*) FROM fund_holding") == 10
    assert _one(conn, "SELECT count(*) FROM fund_holding WHERE constituent_id IS NOT NULL") == 5
    # Alphabet Class A and C become one edge whose weight is the sum, with two evidence rows.
    alpha = conn.execute(
        text(
            "SELECT e.weight, e.confidence, "
            "(SELECT count(*) FROM edge_evidence v WHERE v.edge_id = e.id) "
            "FROM edge e JOIN entity c ON c.id = e.dst_id WHERE c.name = 'Alphabet Inc.'"
        )
    ).one()
    assert alpha.weight > 0 and alpha.confidence == Decimal("0.95") and alpha[2] == 2
    # No edge without evidence (invariant 1).
    assert (
        _one(
            conn,
            "SELECT count(*) FROM edge e WHERE NOT EXISTS "
            "(SELECT 1 FROM edge_evidence v WHERE v.edge_id = e.id)",
        )
        == 0
    )
    assert (
        _one(conn, "SELECT count(*) FROM edge_evidence WHERE span_text NOT LIKE '<invstOrSec>%'")
        == 0
    )


def test_series_name_replaces_the_ticker_placeholder(conn: Connection) -> None:
    fund = _seed(conn)
    _load(conn)
    assert _one(conn, f"SELECT name FROM entity WHERE id = {fund}") == "Vanguard 500 Index Fund"


def test_a_curated_identifier_is_exact_but_a_learned_one_keeps_name_confidence(
    conn: Connection,
) -> None:
    _seed(conn)
    apple = _one(conn, "SELECT id FROM entity WHERE name = 'Apple Inc.'")
    conn.execute(
        text(
            "INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from) "
            "SELECT :e, cusip, 'cusip', 'curated', '2020-01-01' FROM fund_holding LIMIT 0"
        ),
        {"e": apple},
    )
    _load(conn)
    # Apple matched by name first (0.95); the CUSIP it taught is a *learned* identifier.
    _load(conn, datetime(2026, 11, 29, tzinfo=UTC), "0000036405-26-777777")
    row = conn.execute(
        text(
            "SELECT match_method, match_confidence FROM fund_holding "
            "WHERE name = 'Apple Inc' AND known_at = '2026-11-29'"
        )
    ).one()
    assert (row.match_method, row.match_confidence) == (
        "learned_name_identifier",
        Decimal("0.95"),
    )
    # Promote it by hand to a curated identifier: now it is exact.
    conn.execute(text("UPDATE entity_alias SET source = 'curated' WHERE kind = 'cusip'"))
    _load(conn, datetime(2026, 12, 29, tzinfo=UTC), "0000036405-26-888888")
    row = conn.execute(
        text(
            "SELECT match_method, match_confidence FROM fund_holding "
            "WHERE name = 'Apple Inc' AND known_at = '2026-12-29'"
        )
    ).one()
    assert (row.match_method, row.match_confidence) == ("identifier", Decimal("1.0"))


def test_name_match_teaches_the_cusip_so_next_time_it_is_exact(conn: Connection) -> None:
    _seed(conn)
    _load(conn)
    assert (
        _one(
            conn,
            "SELECT count(*) FROM entity_alias WHERE kind = 'cusip' "
            "AND source = 'nport_name_match'",
        )
        >= 4
    )
    _load(conn, datetime(2026, 11, 29, tzinfo=UTC), "0000036405-26-999999")
    methods = (
        conn.execute(
            text(
                "SELECT DISTINCT match_method FROM fund_holding WHERE constituent_id IS NOT NULL "
                "AND known_at = '2026-11-29'"
            )
        )
        .scalars()
        .all()
    )
    assert methods == ["learned_name_identifier"]  # matched by the learned CUSIP, still 0.95


def test_reload_is_idempotent(conn: Connection) -> None:
    _seed(conn)
    _load(conn)
    before = (
        _one(conn, "SELECT count(*) FROM edge"),
        _one(conn, "SELECT count(*) FROM edge_evidence"),
    )
    _load(conn)
    assert (
        _one(conn, "SELECT count(*) FROM edge"),
        _one(conn, "SELECT count(*) FROM edge_evidence"),
    ) == before
    assert _one(conn, "SELECT count(*) FROM fund_holding") == 10


def test_ambiguous_name_is_not_guessed(conn: Connection) -> None:
    _seed(conn)
    _company(conn, "Apple Incorporated")  # normalises to the same name as Apple Inc.
    _load(conn)
    apple = conn.execute(
        text("SELECT constituent_id FROM fund_holding WHERE name = 'Apple Inc'")
    ).scalar_one()
    assert apple is None


def test_newer_report_closes_the_older_edges(conn: Connection) -> None:
    _seed(conn)
    _load(conn)
    body = (FIX / "nport_voo_trimmed.xml").read_text().replace("2026-06-30", "2026-09-30")
    raw = RawPayload(
        "0000036405-26-999999",
        "xml",
        body.encode(),
        KNOWN,
        url=URL,
        published_at=datetime(2026, 11, 29, tzinfo=UTC),
        kind=KIND_FILING,
    )
    doc = conn.execute(
        text(
            "INSERT INTO document (source, source_id, kind, raw_uri, hash) "
            "VALUES ('nport', 'newer', 'nport_p', 's3://x', 'h') RETURNING id"
        )
    ).scalar_one()
    NportConnector(None, []).upsert(
        conn,
        StoredPayload(raw, "s3://x", "h", doc),
        [parse_report(body.encode(), "0000036405-26-999999", datetime(2026, 11, 29, tzinfo=UTC))],
    )
    old = (
        conn.execute(text("SELECT DISTINCT valid_to FROM edge WHERE valid_from = '2026-06-30'"))
        .scalars()
        .all()
    )
    new = (
        conn.execute(text("SELECT DISTINCT valid_to FROM edge WHERE valid_from = '2026-09-30'"))
        .scalars()
        .all()
    )
    assert old == [datetime(2026, 9, 30, tzinfo=UTC)]
    assert new == [None]
    assert date(2026, 6, 30) < date(2026, 9, 30)


def test_name_alias_version_bump_keeps_unchanged_names_open(conn: Connection) -> None:
    from stockiq.entities.names import ensure_name_aliases

    _seed(conn)
    ensure_name_aliases(conn)
    conn.execute(
        text("UPDATE entity_alias SET source = 'normalized_entity_name:v1' WHERE kind = 'name'")
    )
    ensure_name_aliases(conn)
    assert (
        _one(
            conn,
            "SELECT count(*) FROM entity e WHERE e.type = 'company' AND NOT EXISTS "
            "(SELECT 1 FROM entity_alias a WHERE a.entity_id = e.id AND a.kind = 'name' "
            "AND a.valid_to IS NULL)",
        )
        == 0
    )


def test_amendment_for_the_same_period_keeps_both_versions(conn: Connection) -> None:
    _seed(conn)
    _load(conn)
    _load(conn, datetime(2026, 12, 1, tzinfo=UTC), "0000036405-26-AMEND1")
    versions = (
        conn.execute(
            text("SELECT DISTINCT known_at FROM edge WHERE valid_from = '2026-06-30' ORDER BY 1")
        )
        .scalars()
        .all()
    )
    assert len(versions) == 2  # the original is not rewritten by the amendment
    assert _one(conn, "SELECT count(DISTINCT as_of) FROM fund_holding") == 1


def test_reparse_after_an_alias_fix_moves_the_edge_instead_of_doubling_it(
    conn: Connection,
) -> None:
    _seed(conn)
    _load(conn)
    # Make a second "Apple" entity so the same name now resolves ambiguously, then reparse.
    _company(conn, "Apple Incorporated")
    _load(conn)
    apple_edges = _one(
        conn,
        "SELECT count(*) FROM edge e JOIN entity c ON c.id = e.dst_id WHERE c.name LIKE 'Apple%'",
    )
    assert apple_edges <= 1
    total = _one(conn, "SELECT coalesce(sum(weight), 0) FROM edge")
    assert total < 1.5  # one report's weights, not two stacked
