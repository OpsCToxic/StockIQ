"""Company-name normalisation for exact name matching (resolver cascade step 2).

Deliberately conservative: it only removes case, punctuation and legal-form suffixes. Two names
that normalise to the same string are a match; a normalised name shared by several entities is
ambiguous and must not be guessed (see the entity-resolution skill).
"""

import re

from sqlalchemy import Connection, text

NAME_ALIAS_SOURCE = "normalized_entity_name:v4"

_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "plc", "nv", "sa", "ag", "llc", "lp", "se", "cos", "companies",
}  # fmt: skip

# Words that say what kind of business or entity this is, not which one. Two names that share
# only these are not evidence of the same company ("Hartford Financial Services Group" vs
# "PNC Financial Services Group"). Used by the fuzzy matcher's guard.
GENERIC = _SUFFIXES | {
    "and", "of", "the", "group", "holdings", "holding", "financial", "services", "industries",
    "international", "technologies", "technology", "systems", "partners", "trust", "bancorp",
    "bank", "global", "american", "united", "national", "first", "resources", "energy",
    "capital", "enterprises", "solutions", "brands", "sciences", "pharmaceuticals",
    "therapeutics", "entertainment", "communications", "networks", "software", "materials",
    "products", "stores", "foods", "worldwide", "corporate", "fund", "etf", "index",
}  # fmt: skip


# Registry and fund-filing tags: "Corp /DE/", "Corp \DE\", "Corp /NEW", "Co/The". Only a trailing
# two-letter state code or the words "new", "old", "the" after a slash or backslash; a slash
# inside a name ("A/S") is kept.
_TAIL = re.compile(r"\s*[/\\]\s*(?:the|new|old|[a-z]{2})\s*[/\\]?\s*$")


def normalize_name(name: str) -> str:
    s = _TAIL.sub("", name.casefold()).replace("&", " and ")
    # Dotted initials collapse: "N.V." -> "nv", "W.W. Grainger" -> "ww grainger".
    s = re.sub(r"\b([a-z])\.(?=\s|$|[a-z]\.)", r"\1", s)
    s = re.sub(r"['’]", "", s)  # McDonald's -> mcdonalds, not "mcdonald s"
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    tokens = s.split()
    while tokens and tokens[0] == "the":
        tokens.pop(0)
    while len(tokens) > 1 and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def distinctive_tokens(normalized: str) -> set[str]:
    """The words in a normalised name that actually identify the company."""
    return {t for t in normalized.split() if t not in GENERIC}


def ensure_name_aliases(conn: Connection) -> int:
    """Keep exactly one open normalised `name` alias per company, equal to its current name.
    Returns the number of aliases opened.

    Aliases from an older normalisation version are closed; where the new rule yields the same
    string the old row is reopened under the new version, so no entity is left without one.
    """
    conn.execute(
        text(
            """
            UPDATE entity_alias SET valid_to = clock_timestamp()
            WHERE kind = 'name' AND source LIKE 'normalized_entity_name%'
              AND source <> :src AND valid_to IS NULL
            """
        ),
        {"src": NAME_ALIAS_SOURCE},
    )
    rows = conn.execute(
        text(
            """
            SELECT e.id, e.name, e.known_at,
                   coalesce(array_agg(a.alias) FILTER (WHERE a.alias IS NOT NULL), '{}') AS open
            FROM entity e
            LEFT JOIN entity_alias a ON a.entity_id = e.id AND a.kind = 'name'
                 AND a.source = :src AND a.valid_to IS NULL
            WHERE e.type = 'company'
            GROUP BY e.id, e.name, e.known_at
            """
        ),
        {"src": NAME_ALIAS_SOURCE},
    ).all()
    added = 0
    for r in rows:
        wanted = normalize_name(r.name)
        if not wanted or list(r.open) == [wanted]:
            continue
        stale = [a for a in r.open if a != wanted]
        if stale:
            # The entity was renamed (the SEC seed overwrites `entity.name`): the old name stops
            # matching as of now, and the new one starts now. Fund lines naming the new company
            # then match exactly instead of falling through to fuzzy matching.
            conn.execute(
                text(
                    "UPDATE entity_alias SET valid_to = clock_timestamp() WHERE entity_id = :e "
                    "AND kind = 'name' AND source = :src AND valid_to IS NULL AND alias = ANY(:a)"
                ),
                {"e": r.id, "src": NAME_ALIAS_SOURCE, "a": stale},
            )
        if wanted not in r.open:
            conn.execute(
                text(
                    """
                    INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from, known_at)
                    VALUES (:e, :a, 'name', :src, CASE WHEN :renamed THEN clock_timestamp()
                                                       ELSE :at END,
                            CASE WHEN :renamed THEN clock_timestamp() ELSE :at END)
                    ON CONFLICT (entity_id, alias, kind, valid_from)
                    DO UPDATE SET valid_to = NULL, source = EXCLUDED.source
                    """
                ),
                {
                    "e": r.id,
                    "a": wanted,
                    "src": NAME_ALIAS_SOURCE,
                    "at": r.known_at,
                    "renamed": bool(stale),
                },
            )
            added += 1
    return added
