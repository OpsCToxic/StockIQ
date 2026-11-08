"""Run once: `python -m stockiq.connectors.etrade_csv PATH [ACCOUNT_NAME]`."""

import asyncio
import sys
from pathlib import Path

from stockiq.connectors.etrade_csv.connector import EtradeCsvConnector
from stockiq.core.config import get_settings
from stockiq.core.db import get_engine
from stockiq.core.storage import S3RawStore


async def main(path: Path, account: str | None) -> None:
    connector = EtradeCsvConnector(path, account)
    store = S3RawStore(get_settings())
    with get_engine().begin() as conn:  # one transaction: all rows or none
        await connector.run(conn, store)
    export = connector.imported
    assert export is not None
    print(
        f"imported {len(export.positions)} positions + cash {export.cash} "
        f"into '{export.account_name}' as of {export.generated_at:%Y-%m-%d %H:%M %Z}; "
        f"total {export.total_value}"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m stockiq.connectors.etrade_csv PATH [ACCOUNT_NAME]")
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else None))
