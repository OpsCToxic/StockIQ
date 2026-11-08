"""Looks up FIGIs for a list of tickers and stores them as `figi` aliases on the matching entity.

Tickers resolve to an entity through their open `ticker` alias (see sec_tickers). A ticker that
matches no entity, or more than one, is skipped and reported in `self.unlinked`.

The raw payload stored is `{"request": [...jobs], "response": <OpenFIGI response verbatim>}`, so
results can be re-parsed without re-fetching.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

from stockiq.connectors.base import BaseConnector, Cursor, RawPayload, StoredPayload
from stockiq.connectors.openfigi.client import MAPPING_URL, figi_client
from stockiq.connectors.openfigi.models import FigiMatch, FigiMiss, FigiRecord
from stockiq.core.config import Settings

ALIAS_SOURCE = "openfigi"


def _query_ticker(ticker: str) -> str:
    # OpenFIGI spells share classes BRK/B; EDGAR and brokers write BRK-B.
    return ticker.replace("-", "/").replace(".", "/")


class OpenFigiConnector(BaseConnector[FigiRecord]):
    name = "openfigi"
    schedule = "batch"

    def __init__(
        self,
        client: Any,
        tickers: list[str],
        max_jobs: int = 10,
        now: datetime | None = None,
    ) -> None:
        self._client = client
        self._tickers = sorted({t.upper() for t in tickers})
        self._max_jobs = max_jobs
        self._now = now
        self.unlinked: list[str] = []

    @classmethod
    def from_settings(cls, settings: Settings, tickers: list[str]) -> "OpenFigiConnector":
        client, max_jobs = figi_client(settings.openfigi_api_key.get_secret_value())
        return cls(client, tickers, max_jobs)

    async def fetch(self, since: Cursor) -> tuple[list[RawPayload], Cursor]:
        fetched_at = self._now or datetime.now(UTC)
        payloads = []
        for i in range(0, len(self._tickers), self._max_jobs):
            batch = self._tickers[i : i + self._max_jobs]
            jobs = [
                {"idType": "TICKER", "idValue": _query_ticker(t), "exchCode": "US"} for t in batch
            ]
            response = await self._client.request("POST", MAPPING_URL, json=jobs)
            body = json.dumps(
                {"tickers": batch, "request": jobs, "response": response.json()}
            ).encode()
            digest = hashlib.sha256(",".join(batch).encode()).hexdigest()[:16]
            payloads.append(
                RawPayload(
                    source_id=f"figi-{digest}-{fetched_at:%Y-%m-%d}",
                    ext="json",
                    body=body,
                    fetched_at=fetched_at,
                    url=MAPPING_URL,
                    published_at=fetched_at,
                    kind="openfigi_mapping",
                )
            )
        return payloads, {"last_run": fetched_at.isoformat()}

    def parse(self, raw: RawPayload) -> list[FigiRecord]:
        data = json.loads(raw.body)
        records: list[FigiRecord] = []
        for ticker, result in zip(data["tickers"], data["response"], strict=True):
            # A no-match comes back as a "warning" or an "error" depending on the docs page.
            rows = [r for r in result.get("data", []) if r.get("exchCode") == "US"]
            composites = {r["compositeFIGI"] for r in rows if r.get("compositeFIGI")}
            if len(composites) == 1:
                row = next(r for r in rows if r.get("compositeFIGI"))
                records.append(
                    FigiMatch(
                        ticker=ticker,
                        composite_figi=row["compositeFIGI"],
                        share_class_figi=row.get("shareClassFIGI"),
                        name=row.get("name"),
                        security_type=row.get("securityType"),
                    )
                )
            else:
                records.append(
                    FigiMiss(ticker=ticker, reason="ambiguous" if composites else "not_found")
                )
        return records

    def upsert(self, conn: Connection, stored: StoredPayload, records: list[FigiRecord]) -> None:
        at = stored.raw.fetched_at
        for rec in records:
            if isinstance(rec, FigiMiss):
                self.unlinked.append(f"{rec.ticker} ({rec.reason})")
                continue
            entity_ids = (
                conn.execute(
                    text(
                        """
                        SELECT DISTINCT entity_id FROM entity_alias
                        WHERE kind = 'ticker' AND alias = :t AND valid_from <= :at
                          AND (valid_to IS NULL OR valid_to > :at)
                        """
                    ),
                    {"t": rec.ticker, "at": at},
                )
                .scalars()
                .all()
            )
            if len(entity_ids) != 1:
                self.unlinked.append(f"{rec.ticker} ({len(entity_ids)} entities)")
                continue
            conn.execute(
                text(
                    """
                    INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from, known_at)
                    SELECT :eid, :figi, 'figi', :src, :at, :at
                    WHERE NOT EXISTS (
                        SELECT 1 FROM entity_alias
                        WHERE entity_id = :eid AND alias = :figi AND kind = 'figi'
                          AND valid_to IS NULL)
                    """
                ),
                {"eid": entity_ids[0], "figi": rec.composite_figi, "src": ALIAS_SOURCE, "at": at},
            )
