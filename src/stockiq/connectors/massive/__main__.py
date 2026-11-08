"""Run: `python -m stockiq.connectors.massive prices START_DATE` or `... actions START_DATE`.

`prices` loops in chunks of 20 trading days (one transaction each) until caught up with the last
completed session. The free plan allows 5 calls a minute, so a 2-year backfill takes about 100 min.
Safe to stop and rerun: the cursor and the upserts are idempotent.
"""

import asyncio
import sys
from datetime import date

from stockiq.connectors.massive.connector import MassiveActionsConnector, MassivePricesConnector
from stockiq.core.config import get_settings
from stockiq.core.db import get_engine
from stockiq.core.storage import S3RawStore


async def prices(start: date) -> None:
    settings = get_settings()
    connector = MassivePricesConnector.from_settings(settings, start)
    store = S3RawStore(settings)
    try:
        while True:
            with get_engine().begin() as conn:
                result = await connector.run(conn, store)
            print(f"chunk: {result.fetched} trading days, cursor {result.cursor}", flush=True)
            if connector.caught_up:
                break
    finally:
        await connector._client.aclose()


async def actions(start: date) -> None:
    settings = get_settings()
    connector = MassiveActionsConnector.from_settings(settings, start)
    store = S3RawStore(settings)
    try:
        with get_engine().begin() as conn:
            result = await connector.run(conn, store)
        print(f"fetched {result.fetched} pages, {result.records} records; cursor {result.cursor}")
    finally:
        await connector._client.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("prices", "actions"):
        raise SystemExit("usage: python -m stockiq.connectors.massive (prices|actions) START_DATE")
    start_date = date.fromisoformat(sys.argv[2])
    asyncio.run((prices if sys.argv[1] == "prices" else actions)(start_date))
