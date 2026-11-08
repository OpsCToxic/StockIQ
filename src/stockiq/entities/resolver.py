"""Entity resolver: map a mention (name, identifiers, ticker) to an `entity_id` with confidence.

Cascade, stopping at the first confident hit (see the entity-resolution skill):
  1. exact identifier (CIK, LEI, CUSIP, ISIN, FIGI)      1.0, or 0.95 if the identifier was
                                                          itself learned from a name match
  2. exact ticker alias valid at `as_of`                  0.95
  3. unique exact normalised-name alias                   0.95
  4. trigram fuzzy name match, with a margin check        similarity-scaled, capped at 0.89
LLM disambiguation (step 4 in the skill) is not built yet; it must only run on pre-filtered
items and be cached (invariant 8).

Thresholds: >= 0.9 accept; 0.6 to 0.9 accept provisionally and queue for review; below 0.6 do not
link and queue. A name shared by several entities is ambiguous and is never guessed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Connection, text

from stockiq.entities.names import distinctive_tokens, normalize_name

ACCEPT = Decimal("0.9")
PROVISIONAL = Decimal("0.6")
CONF_EXACT_ID = Decimal("1.0")
CONF_ALIAS = Decimal("0.95")
FUZZY_CAP = Decimal("0.89")
FUZZY_FLOOR = Decimal("0.5")  # below this similarity a name is not even a candidate
FUZZY_MARGIN = Decimal("0.1")  # the best candidate must beat the runner-up by this much
LEARNED_SOURCE = "nport_name_match"  # identifiers taught by an accepted name match
# Aliases the system or a reviewer added after seeing real mentions. The evaluation excludes them
# so a gold mention cannot be answered by the very decision it is meant to test.
TAUGHT_SOURCES = (LEARNED_SOURCE, "review")


@dataclass(frozen=True)
class Mention:
    name: str | None = None
    ticker: str | None = None
    cik: str | None = None
    lei: str | None = None
    cusip: str | None = None
    isin: str | None = None
    figi: str | None = None


@dataclass(frozen=True)
class Candidate:
    entity_id: int
    name: str
    score: Decimal
    via: str


@dataclass
class Resolution:
    entity_id: int | None
    confidence: Decimal
    method: str
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        """Linked into the graph (possibly provisionally)."""
        return self.entity_id is not None and self.confidence >= PROVISIONAL

    @property
    def needs_review(self) -> bool:
        return self.confidence < ACCEPT and (self.entity_id is not None or bool(self.candidates))


NONE = Resolution(None, Decimal(0), "none")


def resolve(
    conn: Connection, mention: Mention, as_of: datetime, *, use_learned: bool = True
) -> Resolution:
    """`use_learned=False` ignores identifiers taught by name matches; the evaluation uses it so
    a test mention cannot be answered by the very match it is meant to check."""
    for step in (_by_identifier, _by_ticker, _by_exact_name, _by_fuzzy_name):
        result = step(conn, mention, as_of, use_learned)
        if result is not None:
            return result
    return NONE


def _entities(conn: Connection, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = conn.execute(text("SELECT id, name FROM entity WHERE id = ANY(:i)"), {"i": ids}).all()
    return {r.id: r.name for r in rows}


def _by_identifier(
    conn: Connection, m: Mention, as_of: datetime, use_learned: bool
) -> Resolution | None:
    direct = (("cik", m.cik, "cik"), ("lei", m.lei, "lei"))
    for column, value, label in direct:
        if value and value.strip("0N/A "):
            ids = (
                conn.execute(
                    text(f"SELECT id FROM entity WHERE {column} = :v"),  # noqa: S608 - fixed names
                    {"v": value},
                )
                .scalars()
                .all()
            )
            if len(ids) == 1:
                return Resolution(ids[0], CONF_EXACT_ID, f"identifier:{label}")
    for kind, value in (("cusip", m.cusip), ("isin", m.isin), ("figi", m.figi)):
        if not value or not value.strip("0N/A "):
            continue
        rows = conn.execute(
            text(
                "SELECT DISTINCT entity_id, source FROM entity_alias "
                "WHERE kind = :k AND alias = :v AND valid_to IS NULL"
            ),
            {"k": kind, "v": value},
        ).all()
        if use_learned is False:
            rows = [r for r in rows if r.source not in TAUGHT_SOURCES]
        if len({r.entity_id for r in rows}) == 1:
            learned = all(r.source == LEARNED_SOURCE for r in rows)
            # An identifier we learned from a name match keeps the name match's confidence, so a
            # wrong name match cannot be laundered into a certain one.
            return Resolution(
                rows[0].entity_id,
                CONF_ALIAS if learned else CONF_EXACT_ID,
                f"identifier:{kind}:learned" if learned else f"identifier:{kind}",
            )
    return None


def _by_ticker(
    conn: Connection, m: Mention, as_of: datetime, use_learned: bool
) -> Resolution | None:
    if not m.ticker:
        return None
    ids = (
        conn.execute(
            text(
                """
                SELECT DISTINCT entity_id FROM entity_alias
                WHERE kind = 'ticker' AND alias = :t AND valid_from <= :at
                  AND (valid_to IS NULL OR valid_to > :at)
                  AND (CAST(:ul AS boolean) OR source <> ALL(:taught))
                """
            ),
            {
                "t": m.ticker.upper(),
                "at": as_of,
                "ul": use_learned,
                "taught": list(TAUGHT_SOURCES),
            },
        )
        .scalars()
        .all()
    )
    if len(ids) == 1:
        return Resolution(ids[0], CONF_ALIAS, "ticker")
    if len(ids) > 1:
        names = _entities(conn, list(ids))
        return Resolution(
            None,
            Decimal("0.5"),
            "ambiguous_ticker",
            [Candidate(i, names[i], Decimal("0.5"), "ticker") for i in ids],
        )
    return None


def _by_exact_name(
    conn: Connection, m: Mention, as_of: datetime, use_learned: bool
) -> Resolution | None:
    norm = normalize_name(m.name or "")
    if not norm:
        return None
    ids = (
        conn.execute(
            text(
                "SELECT DISTINCT entity_id FROM entity_alias "
                "WHERE kind = 'name' AND alias = :n AND valid_to IS NULL "
                "AND (CAST(:ul AS boolean) OR source <> ALL(:taught))"
            ),
            {"n": norm, "ul": use_learned, "taught": list(TAUGHT_SOURCES)},
        )
        .scalars()
        .all()
    )
    if len(ids) == 1:
        return Resolution(ids[0], CONF_ALIAS, "exact_name")
    if len(ids) > 1:
        names = _entities(conn, list(ids))
        return Resolution(
            None,
            Decimal("0.5"),
            "ambiguous_name",
            [Candidate(i, names[i], Decimal("0.5"), "exact_name") for i in ids],
        )
    return None


def _by_fuzzy_name(
    conn: Connection, m: Mention, as_of: datetime, use_learned: bool
) -> Resolution | None:
    norm = normalize_name(m.name or "")
    if not norm:
        return None
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (a.entity_id) a.entity_id, e.name, a.alias,
                   similarity(a.alias, :n) AS sim
            FROM entity_alias a JOIN entity e ON e.id = a.entity_id
            WHERE a.kind = 'name' AND a.valid_to IS NULL AND a.alias % :n
              AND similarity(a.alias, :n) >= :floor
              AND (CAST(:ul AS boolean) OR a.source <> ALL(:taught))
            ORDER BY a.entity_id, sim DESC
            """
        ),
        {
            "n": norm,
            "floor": float(FUZZY_FLOOR),
            "ul": use_learned,
            "taught": list(TAUGHT_SOURCES),
        },
    ).all()
    # Guard: a candidate must share at least one distinctive word with the mention.
    # Sharing only "Financial Services Group" is how Hartford gets matched to PNC.
    wanted = distinctive_tokens(norm)
    rows = [r for r in rows if wanted & distinctive_tokens(r.alias)]
    rows = sorted(rows, key=lambda r: r.sim, reverse=True)[:5]
    if not rows:
        return None
    candidates = [
        Candidate(r.entity_id, r.name, Decimal(str(round(r.sim, 4))), "fuzzy") for r in rows
    ]
    best = candidates[0]
    runner_up = candidates[1].score if len(candidates) > 1 else Decimal(0)
    confidence = min(FUZZY_CAP, best.score)
    if best.score - runner_up < FUZZY_MARGIN:
        # Too close to call: keep the candidates for a reviewer, link nothing.
        return Resolution(None, min(confidence, Decimal("0.55")), "fuzzy_ambiguous", candidates)
    if confidence < PROVISIONAL:
        return Resolution(None, confidence, "fuzzy_weak", candidates)
    return Resolution(best.entity_id, confidence, "fuzzy_name", candidates)
