"""Company-name normalisation for exact name matching (resolver cascade step 2).

Deliberately conservative: it only removes case, punctuation and legal-form suffixes. Two names
that normalise to the same string are a match; a normalised name shared by several entities is
ambiguous and must not be guessed (see the entity-resolution skill).
"""

import re

from sqlalchemy import Connection, text

NAME_ALIAS_SOURCE = "normalized_entity_name:v2"

_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "plc", "nv", "sa", "ag", "llc", "lp", "se",
}  # fmt: skip


# Registry and fund-filing tags: "Corp /DE/", "Corp /NEW", "Co/The". Only a trailing "/xx/" state
# code or the words "new", "old", "the" after a slash; a slash inside a name ("A/S") is kept.
_TAIL = re.compile(r"\s*/\s*(?:the|new|old|[a-z]{2})\s*/?\s*$")


def normalize_name(name: str) -> str:
    s = _TAIL.sub("", name.casefold()).replace("&", " and ")
    s = re.sub(r"['’]", "", s)  # McDonald's -> mcdonalds, not "mcdonald s"
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    tokens = s.split()
    while tokens and tokens[0] == "the":
        tokens.pop(0)
    while len(tokens) > 1 and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def ensure_name_aliases(conn: Connection) -> int:
    """Add a normalised `name` alias for every entity that lacks one. Returns rows added.

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
            SELECT e.id, e.name, e.known_at FROM entity e
            WHERE e.type = 'company' AND NOT EXISTS (
                SELECT 1 FROM entity_alias a
                WHERE a.entity_id = e.id AND a.kind = 'name' AND a.source = :src)
            """
        ),
        {"src": NAME_ALIAS_SOURCE},
    ).all()
    params = [
        {"e": r.id, "a": normalize_name(r.name), "at": r.known_at, "src": NAME_ALIAS_SOURCE}
        for r in rows
        if normalize_name(r.name)
    ]
    if params:
        conn.execute(
            text(
                """
                INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from, known_at)
                VALUES (:e, :a, 'name', :src, :at, :at)
                ON CONFLICT (entity_id, alias, kind, valid_from)
                DO UPDATE SET valid_to = NULL, source = EXCLUDED.source
                """
            ),
            params,
        )
    return len(params)
