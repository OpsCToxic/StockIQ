"""Run once: `python -m stockiq.connectors.nport [TICKER ...]`.

With no tickers it covers every fund you currently hold. Tickers are mapped to SEC series ids
through the entity master (run `sec_tickers` first).

`python -m stockiq.connectors.nport reparse` re-processes every stored filing from raw storage,
without fetching. Use it after the resolver or its aliases change (raw-first, invariant 4).
"""

import asyncio
import sys

from sqlalchemy import text

from stockiq.connectors.nport.connector import NportConnector
from stockiq.core.config import get_settings
from stockiq.core.db import get_engine
from stockiq.core.storage import S3RawStore


def _series_for(tickers: list[str]) -> list[str]:
    with get_engine().connect() as conn:
        if tickers:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT e.series_id FROM entity e
                    JOIN entity_alias a ON a.entity_id = e.id
                    WHERE e.type = 'fund' AND e.series_id IS NOT NULL AND a.kind = 'ticker'
                      AND a.alias = ANY(:t) AND a.valid_to IS NULL
                    """
                ),
                {"t": [t.upper() for t in tickers]},
            )
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT e.series_id FROM holding h
                    JOIN entity e ON e.id = h.security_id
                    WHERE e.type = 'fund' AND e.series_id IS NOT NULL
                    """
                )
            )
        return [r[0] for r in rows]


async def main(tickers: list[str]) -> None:
    series = _series_for(tickers)
    if not series:
        raise SystemExit("no fund series found for those tickers (or no funds held)")
    settings = get_settings()
    connector = NportConnector.from_settings(settings, series)
    store = S3RawStore(settings)
    try:
        with get_engine().begin() as conn:
            result = await connector.run(conn, store)
    finally:
        await connector._client.aclose()
    print(f"series {series}: fetched {result.fetched} payloads, {result.records} reports")


def reparse() -> None:
    """Re-run parse and upsert over every stored N-PORT filing, from raw storage."""
    from stockiq.connectors.base import RawPayload, StoredPayload
    from stockiq.connectors.nport.connector import KIND_FILING, parse_report

    store = S3RawStore(get_settings())
    connector = NportConnector(None, [])
    with get_engine().begin() as conn:
        docs = conn.execute(
            text(
                "SELECT id, source_id, raw_uri, hash, url, published_at, ingested_at "
                "FROM document WHERE source = 'nport' AND kind = :k ORDER BY published_at"
            ),
            {"k": KIND_FILING},
        ).all()
        for d in docs:
            body = store.get(d.raw_uri)
            raw = RawPayload(
                d.source_id,
                "xml",
                body,
                d.ingested_at,
                url=d.url,
                published_at=d.published_at,
                kind=KIND_FILING,
            )
            stored = StoredPayload(raw, d.raw_uri, d.hash, d.id)
            connector.upsert(conn, stored, [parse_report(body, d.source_id, d.published_at)])
            print(f"reparsed {d.source_id}")
    print(f"{len(docs)} filings re-processed from raw storage")


if __name__ == "__main__":
    if sys.argv[1:] == ["reparse"]:
        reparse()
    else:
        asyncio.run(main(sys.argv[1:]))
