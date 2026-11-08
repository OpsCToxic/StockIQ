"""Run once: `python -m stockiq.connectors.nport [TICKER ...]`.

With no tickers it covers every fund you currently hold. Tickers are mapped to SEC series ids
through the entity master (run `sec_tickers` first).
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


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
