"""Needs `make up` and `make migrate`. Runs inside a transaction that is rolled back."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Connection, text

from stockiq.core.db import get_engine
from stockiq.entities.eval import score, summarise
from stockiq.entities.names import ensure_name_aliases

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 8, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias, review_queue, document CASCADE"))
        yield c
        trans.rollback()


def _row(name: str, cusip: str, expected_cik: str) -> dict[str, str]:
    return {
        "cusip": cusip, "isin": "", "lei": "", "name": name, "expected_cik": expected_cik,
        "expected_name": "", "label_source": "t", "note": "", "reviewed": "yes",
    }  # fmt: skip


def _company(conn: Connection, name: str, cik: str) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO entity (name, type, cik, known_at) "
                "VALUES (:n, 'company', :c, '2020-01-01') RETURNING id"
            ),
            {"n": name, "c": cik},
        ).scalar_one()
    )


def test_scores_a_correct_and_a_wrong_link(conn: Connection) -> None:
    _company(conn, "Apple Inc.", "0000320193")
    _company(conn, "Microsoft Corp", "0000789019")
    ensure_name_aliases(conn)
    rows = [_row("Apple Inc", "1", "0000320193"), _row("Microsoft Corporation", "2", "0000000001")]
    s = summarise(score(conn, rows, NOW))
    assert (s["linked"], s["correct"], s["precision"]) == (2, 1, 0.5)


def test_a_reviewers_alias_cannot_answer_the_evaluation(conn: Connection) -> None:
    """Otherwise reviewing a queue item would make that same line look 'resolved' in the gate."""
    exxon = _company(conn, "ExxonMobil Holdings Corp", "0002115436")
    ensure_name_aliases(conn)
    conn.execute(
        text(
            "INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from) "
            "VALUES (:e, '30231G102', 'cusip', 'review', '2020-01-01')"
        ),
        {"e": exxon},
    )
    rows = [
        {**_row("Exxon Mobil Corp", "30231G102", "0002115436"), "cusip": "30231G102"},
    ]
    scored = score(conn, rows, NOW)
    assert scored[0].entity_cik is None  # the reviewed CUSIP alias was ignored
