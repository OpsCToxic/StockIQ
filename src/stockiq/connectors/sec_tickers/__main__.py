"""Run once: `python -m stockiq.connectors.sec_tickers`."""

import asyncio

from stockiq.connectors.sec_tickers.connector import SecTickersConnector
from stockiq.core.config import get_settings
from stockiq.core.db import get_engine
from stockiq.core.storage import S3RawStore


async def main() -> None:
    settings = get_settings()
    connector = SecTickersConnector.from_settings(settings)
    store = S3RawStore(settings)
    try:
        with get_engine().begin() as conn:
            result = await connector.run(conn, store)
    finally:
        await connector._client.aclose()
    print(f"fetched {result.fetched} files, parsed {result.records} records")


if __name__ == "__main__":
    asyncio.run(main())
