"""Seeds the entity master from the SEC ticker files.

One company entity per CIK (share classes become extra ticker aliases). One fund entity per SEC
series id, with the trust CIK kept in `filer_cik`. Ticker aliases that disappear from the file are
closed (`valid_to`), so a reused ticker never resolves to the old company after the change.
"""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

from stockiq.connectors.base import BaseConnector, Cursor, RawPayload, StoredPayload
from stockiq.connectors.sec_tickers.client import COMPANY_URL, FUND_URL
from stockiq.connectors.sec_tickers.models import SecCompany, SecFund, SecRecord
from stockiq.core.config import Settings

ALIAS_SOURCE = "sec_company_tickers"
UNKNOWN_START = datetime(1970, 1, 1, tzinfo=UTC)
KIND_COMPANY = "sec_tickers_exchange"
KIND_FUND = "sec_tickers_mf"


def _cik(value: int | str) -> str:
    return str(int(value)).zfill(10)


class SecTickersConnector(BaseConnector[SecRecord]):
    name = "sec_tickers"
    schedule = "batch"

    def __init__(self, client: Any, now: datetime | None = None) -> None:
        self._client = client
        self._now = now

    @classmethod
    def from_settings(cls, settings: Settings) -> "SecTickersConnector":
        from stockiq.connectors.sec_tickers.client import sec_client

        return cls(sec_client(settings.sec_user_agent))

    async def fetch(self, since: Cursor) -> tuple[list[RawPayload], Cursor]:
        fetched_at = self._now or datetime.now(UTC)
        day = f"{fetched_at:%Y-%m-%d}"
        payloads = []
        for url, kind in ((COMPANY_URL, KIND_COMPANY), (FUND_URL, KIND_FUND)):
            response = await self._client.get(url)
            payloads.append(
                RawPayload(
                    source_id=f"{kind}-{day}",
                    ext="json",
                    body=response.content,
                    fetched_at=fetched_at,
                    url=url,
                    published_at=fetched_at,  # the file has no publish time; use fetch time
                    kind=kind,
                )
            )
        return payloads, {"last_run": fetched_at.isoformat()}

    def parse(self, raw: RawPayload) -> list[SecRecord]:
        data = json.loads(raw.body)
        fields: list[str] = data["fields"]
        rows = [dict(zip(fields, row, strict=True)) for row in data["data"]]
        records: list[SecRecord] = []
        if raw.kind == KIND_COMPANY:
            for r in rows:
                if r.get("ticker") and r.get("name"):
                    records.append(
                        SecCompany(
                            cik=_cik(r["cik"]),
                            name=r["name"],
                            ticker=str(r["ticker"]).upper(),
                            exchange=r.get("exchange"),
                        )
                    )
        elif raw.kind == KIND_FUND:
            for r in rows:
                if r.get("symbol") and r.get("seriesId"):
                    records.append(
                        SecFund(
                            filer_cik=_cik(r["cik"]),
                            series_id=r["seriesId"],
                            class_id=r["classId"],
                            ticker=str(r["symbol"]).upper(),
                        )
                    )
        else:
            raise ValueError(f"unknown payload kind {raw.kind!r}")
        return records

    def upsert(self, conn: Connection, stored: StoredPayload, records: list[SecRecord]) -> None:
        at = stored.raw.fetched_at
        companies = [r for r in records if isinstance(r, SecCompany)]
        funds = [r for r in records if isinstance(r, SecFund)]
        if companies:
            self._upsert_companies(conn, companies, at)
        if funds:
            self._upsert_funds(conn, funds, at)

    def _upsert_companies(self, conn: Connection, rows: list[SecCompany], at: datetime) -> None:
        # Names within a CIK can differ per share class; keep the first listed.
        by_cik: dict[str, SecCompany] = {}
        for r in rows:
            by_cik.setdefault(r.cik, r)
        conn.execute(
            text(
                """
                INSERT INTO entity (name, type, cik, public, known_at)
                VALUES (:name, 'company', :cik, true, :at)
                ON CONFLICT (cik) WHERE cik IS NOT NULL DO UPDATE SET name = EXCLUDED.name
                """
            ),
            [{"name": r.name, "cik": r.cik, "at": at} for r in by_cik.values()],
        )
        self._sync_aliases(conn, [(r.cik, r.ticker) for r in rows], "company", at)

    def _upsert_funds(self, conn: Connection, rows: list[SecFund], at: datetime) -> None:
        by_series: dict[str, SecFund] = {}
        for r in rows:
            by_series.setdefault(r.series_id, r)
        # SEC's fund file has no names. The ticker stands in until N-PORT supplies the series name.
        conn.execute(
            text(
                """
                INSERT INTO entity (name, type, series_id, filer_cik, public, known_at)
                VALUES (:name, 'fund', :series, :filer, true, :at)
                ON CONFLICT (series_id) WHERE series_id IS NOT NULL
                DO UPDATE SET filer_cik = EXCLUDED.filer_cik
                """
            ),
            [
                {"name": r.ticker, "series": r.series_id, "filer": r.filer_cik, "at": at}
                for r in by_series.values()
            ],
        )
        self._sync_aliases(conn, [(r.series_id, r.ticker) for r in rows], "fund", at)

    def _sync_aliases(
        self, conn: Connection, pairs: list[tuple[str, str]], kind: str, at: datetime
    ) -> None:
        """Open new ticker aliases and close ones no longer in the file, for this source only.

        `kind` is "company" (pairs are cik, ticker) or "fund" (pairs are series_id, ticker).
        """
        conn.execute(text("CREATE TEMP TABLE IF NOT EXISTS seed_pair (key text, ticker text)"))
        conn.execute(text("TRUNCATE seed_pair"))
        conn.execute(
            text("INSERT INTO seed_pair (key, ticker) VALUES (:k, :t)"),
            [{"k": k, "t": t} for k, t in sorted(set(pairs))],
        )
        match = "(CASE WHEN e.type = 'fund' THEN e.series_id ELSE e.cik END) = p.key"
        conn.execute(
            text(
                f"""
                UPDATE entity_alias a SET valid_to = :at
                FROM entity e
                WHERE a.entity_id = e.id AND a.source = :src AND a.kind = 'ticker'
                  AND a.valid_to IS NULL AND e.type = :kind
                  AND NOT EXISTS (
                    SELECT 1 FROM seed_pair p WHERE {match} AND p.ticker = a.alias)
                """  # noqa: S608 - interpolates a constant, no user input
            ),
            {"at": at, "src": ALIAS_SOURCE, "kind": kind},
        )
        # The very first seed of this kind has no history to go on: its aliases start "unknown"
        # (epoch), not on the day we happened to fetch. Later seeds record real changes.
        first_seed = (
            conn.execute(
                text(
                    "SELECT 1 FROM entity_alias a JOIN entity e ON e.id = a.entity_id "
                    "WHERE a.source = :src AND a.kind = 'ticker' AND e.type = :kind LIMIT 1"
                ),
                {"src": ALIAS_SOURCE, "kind": kind},
            ).first()
            is None
        )
        valid_from = UNKNOWN_START if first_seed else at
        conn.execute(
            text(
                f"""
                INSERT INTO entity_alias (entity_id, alias, kind, source, valid_from, known_at)
                SELECT e.id, p.ticker, 'ticker', :src, :vf, :at
                FROM seed_pair p JOIN entity e ON {match} AND e.type = :kind
                WHERE NOT EXISTS (
                    SELECT 1 FROM entity_alias a
                    WHERE a.entity_id = e.id AND a.alias = p.ticker
                      AND a.kind = 'ticker' AND a.valid_to IS NULL)
                """  # noqa: S608 - interpolates a constant, no user input
            ),
            {"src": ALIAS_SOURCE, "at": at, "kind": kind, "vf": valid_from},
        )
