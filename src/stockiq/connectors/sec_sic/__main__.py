"""Run once: `python -m stockiq.connectors.sec_sic [CIK ...]`.

With no CIKs it classifies every company that appears in your look-through: direct holdings and
anything a fund contains or references through swaps. About 5 requests a second.
"""

import asyncio
import sys

from sqlalchemy import text

from stockiq.connectors.sec_sic.connector import SecSicConnector
from stockiq.core.config import get_settings
from stockiq.core.db import get_engine
from stockiq.core.storage import S3RawStore


def _ciks() -> list[str]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT e.cik FROM entity e
                WHERE e.type = 'company' AND e.cik IS NOT NULL AND (
                    e.id IN (SELECT dst_id FROM edge WHERE type IN ('CONTAINS', 'SYNTHETIC'))
                    OR e.id IN (SELECT security_id FROM holding))
                """
            )
        )
        return [r[0] for r in rows]


async def main(ciks: list[str]) -> None:
    ciks = ciks or _ciks()
    if not ciks:
        raise SystemExit("no companies to classify; run the N-PORT connector first")
    settings = get_settings()
    connector = SecSicConnector.from_settings(settings, ciks)
    store = S3RawStore(settings)
    try:
        with get_engine().begin() as conn:
            result = await connector.run(conn, store)
    finally:
        await connector._client.aclose()
    print(
        f"fetched {result.fetched} companies, classified {result.records}; "
        f"skipped: {connector.skipped[:10] or 'none'}"
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
