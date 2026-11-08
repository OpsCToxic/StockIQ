"""Run once: `python -m stockiq.connectors.openfigi AAPL GOOGL VOO`."""

import asyncio
import sys

from stockiq.connectors.openfigi.connector import OpenFigiConnector
from stockiq.core.config import get_settings
from stockiq.core.db import get_engine
from stockiq.core.storage import S3RawStore


async def main(tickers: list[str]) -> None:
    settings = get_settings()
    connector = OpenFigiConnector.from_settings(settings, tickers)
    store = S3RawStore(settings)
    try:
        with get_engine().begin() as conn:
            result = await connector.run(conn, store)
    finally:
        await connector._client.aclose()
    print(f"looked up {result.records} tickers; not linked: {connector.unlinked or 'none'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m stockiq.connectors.openfigi TICKER [TICKER ...]")
    asyncio.run(main(sys.argv[1:]))
