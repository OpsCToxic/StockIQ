"""Needs `make up` and `make migrate`. Runs inside a transaction that is rolled back."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Connection, text

from stockiq.core.db import get_engine
from stockiq.entities import review
from stockiq.entities.names import ensure_name_aliases
from stockiq.entities.resolver import Mention, resolve

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 8, tzinfo=UTC)
OLD = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def conn() -> Iterator[Connection]:
    with get_engine().connect() as c:
        trans = c.begin()
        c.execute(text("TRUNCATE entity, entity_alias, review_queue, document CASCADE"))
        yield c
        trans.rollback()


def _company(conn: Connection, name: str, cik: str | None = None, lei: str | None = None) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO entity (name, type, cik, lei, known_at) "
                "VALUES (:n, 'company', :c, :l, '2020-01-01') RETURNING id"
            ),
            {"n": name, "c": cik, "l": lei},
        ).scalar_one()
    )


def _alias(
    conn: Connection,
    eid: int,
    alias: str,
    kind: str,
    source: str = "curated",
    valid_from: datetime = OLD,
    valid_to: datetime | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from, valid_to) "
            "VALUES (:e, :a, :k, :s, :f, :t)"
        ),
        {"e": eid, "a": alias, "k": kind, "s": source, "f": valid_from, "t": valid_to},
    )


def test_exact_identifiers_are_certain(conn: Connection) -> None:
    apple = _company(conn, "Apple Inc.", cik="0000320193", lei="HWUPKR0MPOU8FGXBT394")
    _alias(conn, apple, "037833100", "cusip")
    for mention, method in (
        (Mention(cik="0000320193"), "identifier:cik"),
        (Mention(lei="HWUPKR0MPOU8FGXBT394"), "identifier:lei"),
        (Mention(cusip="037833100"), "identifier:cusip"),
    ):
        r = resolve(conn, mention, NOW)
        assert (r.entity_id, r.confidence, r.method) == (apple, Decimal("1.0"), method)
        assert not r.needs_review


def test_a_learned_identifier_keeps_name_confidence_and_can_be_ignored(conn: Connection) -> None:
    apple = _company(conn, "Apple Inc.")
    _alias(conn, apple, "037833100", "cusip", source="nport_name_match")
    r = resolve(conn, Mention(cusip="037833100"), NOW)
    assert (r.confidence, r.method) == (Decimal("0.95"), "identifier:cusip:learned")
    # The evaluation must not be answered by the very match it is checking.
    assert resolve(conn, Mention(cusip="037833100"), NOW, use_learned=False).entity_id is None


def test_ticker_is_resolved_as_of_the_document_date(conn: Connection) -> None:
    old_co, new_co = _company(conn, "Old Co"), _company(conn, "New Co")
    _alias(conn, old_co, "XYZ", "ticker", valid_to=datetime(2024, 1, 1, tzinfo=UTC))
    _alias(conn, new_co, "XYZ", "ticker", valid_from=datetime(2024, 1, 1, tzinfo=UTC))
    assert (
        resolve(conn, Mention(ticker="XYZ"), datetime(2023, 6, 1, tzinfo=UTC)).entity_id == old_co
    )
    assert (
        resolve(conn, Mention(ticker="XYZ"), datetime(2025, 6, 1, tzinfo=UTC)).entity_id == new_co
    )


def test_exact_name_ignores_case_punctuation_and_legal_suffix(conn: Connection) -> None:
    deere = _company(conn, "DEERE & CO")
    ensure_name_aliases(conn)
    r = resolve(conn, Mention(name="Deere & Company"), NOW)
    assert (r.entity_id, r.confidence, r.method) == (deere, Decimal("0.95"), "exact_name")


def test_a_name_shared_by_two_entities_is_ambiguous_and_never_guessed(conn: Connection) -> None:
    a, b = _company(conn, "Acme Corp"), _company(conn, "Acme Inc")
    ensure_name_aliases(conn)
    r = resolve(conn, Mention(name="ACME"), NOW)
    assert r.entity_id is None and r.method == "ambiguous_name" and r.needs_review
    assert {c.entity_id for c in r.candidates} == {a, b}


def test_fuzzy_match_is_provisional_and_goes_to_review(conn: Connection) -> None:
    target = _company(conn, "Applied Materials Holdings")
    _company(conn, "Banana Republic Foods")
    ensure_name_aliases(conn)
    r = resolve(conn, Mention(name="Applied Materials"), NOW)
    assert r.entity_id == target and r.method == "fuzzy_name"
    assert Decimal("0.6") <= r.confidence < Decimal("0.9")
    assert r.accepted and r.needs_review  # linked provisionally AND queued


def test_two_close_candidates_link_nothing(conn: Connection) -> None:
    _company(conn, "Northern Star Holdings East")
    _company(conn, "Northern Star Holdings West")
    ensure_name_aliases(conn)
    r = resolve(conn, Mention(name="Northern Star Holdings"), NOW)
    assert r.entity_id is None and r.needs_review
    assert len(r.candidates) == 2


def test_sharing_only_generic_words_is_not_a_match(conn: Connection) -> None:
    """Hartford was once matched to PNC because both are 'Financial Services Group'."""
    _company(conn, "PNC Financial Services Group, Inc.")
    ensure_name_aliases(conn)
    r = resolve(conn, Mention(name="Hartford Financial Services Group Inc/The"), NOW)
    assert r.entity_id is None and not r.candidates


def test_word_order_and_initials_still_match_when_a_distinctive_word_is_shared(
    conn: Connection,
) -> None:
    target = _company(conn, "SMITH A O CORP")
    _company(conn, "Banana Republic Foods")
    ensure_name_aliases(conn)
    r = resolve(conn, Mention(name="A O Smith Corp"), NOW)
    assert r.entity_id == target and r.confidence >= Decimal("0.6")


def test_an_unrelated_name_is_not_even_a_candidate(conn: Connection) -> None:
    _company(conn, "Apple Inc.")
    ensure_name_aliases(conn)
    r = resolve(conn, Mention(name="Zzyzx Quarry Partners"), NOW)
    assert r.entity_id is None and not r.candidates and not r.needs_review


def test_accepting_a_review_item_teaches_exact_matching(conn: Connection) -> None:
    target = _company(conn, "ExxonMobil Holdings Corp")
    ensure_name_aliases(conn)
    mention = Mention(name="Exxon Mobil Corp", cusip="30231G102")
    first = resolve(conn, mention, NOW)
    assert first.entity_id != target or first.needs_review  # not certain before review
    review.enqueue(conn, "t", "ref-1", mention, first)
    (item,) = review.pending(conn)
    review.accept(conn, int(item["id"]), target)  # type: ignore[arg-type]
    after = resolve(conn, mention, NOW)
    assert (after.entity_id, after.confidence) == (target, Decimal("1.0"))  # curated, exact
    assert resolve(conn, Mention(name="Exxon Mobil Corp"), NOW).entity_id == target
    assert review.pending(conn) == []


def test_decided_items_are_not_reopened_or_decided_twice(conn: Connection) -> None:
    target = _company(conn, "Applied Materials Holdings")
    ensure_name_aliases(conn)
    mention = Mention(name="Applied Materials")
    res = resolve(conn, mention, NOW)
    review.enqueue(conn, "t", "ref-2", mention, res)
    (item,) = review.pending(conn)
    review.reject(conn, int(item["id"]))  # type: ignore[arg-type]
    review.enqueue(conn, "t", "ref-2", mention, res)  # same mention shows up again
    assert review.pending(conn) == []  # a rejection is final
    with pytest.raises(ValueError, match="not pending"):
        review.reject(conn, int(item["id"]))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="already rejected"):
        review.accept(conn, int(item["id"]), target)  # type: ignore[arg-type]


def test_accepting_an_unknown_entity_is_refused(conn: Connection) -> None:
    mention = Mention(name="Whatever Co")
    review.enqueue(conn, "t", "ref-3", mention, resolve(conn, mention, NOW))
    conn.execute(
        text(
            "UPDATE review_queue SET confidence = 0.5, method = 'fuzzy_weak' "
            "WHERE source_ref = 'ref-3'"
        )
    )
    (item,) = review.pending(conn)
    with pytest.raises(ValueError, match="no entity"):
        review.accept(conn, int(item["id"]), 999999999)  # type: ignore[arg-type]
