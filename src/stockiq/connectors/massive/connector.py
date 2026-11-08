"""Massive (formerly Polygon) daily prices and corporate actions. See ADR 0005 and 0006.

Prices come from one grouped-daily call per trading day, **unadjusted**. Splits and dividends come
from their own endpoints; adjusted series are computed later from `corporate_action` using only
rows known by the as-of date.

Facts verified against the live API on 2026-11-08: grouped-daily returns HTTP 200 with zero results
on weekends and holidays; asking for today before the close returns 403; the bar timestamp `t` is
the 4 PM ET close in UTC; volume can be fractional; `next_url` carries a cursor but no key, so the
Bearer header must be sent on every page.
"""

import gzip
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, text

from stockiq.connectors.base import BaseConnector, Cursor, RawPayload, StoredPayload
from stockiq.connectors.massive.client import BASE_URL, massive_client
from stockiq.connectors.massive.models import (
    Dividend,
    MassiveRecord,
    PriceBar,
    Split,
)
from stockiq.core.config import Settings

NY = ZoneInfo("America/New_York")
SOURCE = "massive"
KIND_GROUPED = "massive_grouped_daily"
KIND_DIVIDENDS = "massive_dividends"
KIND_SPLITS = "massive_splits"
GROUPED_URL = BASE_URL + "/v2/aggs/grouped/locale/us/market/stocks/{day}"
DIVIDENDS_URL = BASE_URL + "/stocks/v1/dividends"
SPLITS_URL = BASE_URL + "/stocks/v1/splits"
ACTIONS_OVERLAP = timedelta(days=30)  # late declarations; the upsert is idempotent


def weekdays_between(after: date, through: date) -> list[date]:
    """Weekdays in (after, through]. Holidays are included; the API returns no rows for them."""
    days = []
    d = after + timedelta(days=1)
    while d <= through:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def last_completed_session_date(now: datetime) -> date:
    """Yesterday in New York. The free plan refuses today's data before the end of day."""
    return now.astimezone(NY).date() - timedelta(days=1)


def _body(raw: RawPayload) -> dict[str, Any]:
    body = raw.body
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    data: dict[str, Any] = json.loads(body)
    return data


class MassivePricesConnector(BaseConnector[MassiveRecord]):
    name = "massive_prices"
    schedule = "batch"

    def __init__(
        self,
        client: Any,
        start: date,
        max_days: int = 20,
        now: datetime | None = None,
    ) -> None:
        self._client = client
        self._start = start
        self._max_days = max_days
        self._now = now
        self.caught_up = False

    @classmethod
    def from_settings(
        cls, settings: Settings, start: date, max_days: int = 20
    ) -> "MassivePricesConnector":
        client = massive_client(settings.massive_api_key.get_secret_value())
        return cls(client, start, max_days)

    async def fetch(self, since: Cursor) -> tuple[list[RawPayload], Cursor]:
        now = self._now or datetime.now(UTC)
        last = (
            date.fromisoformat(since["last_date"])
            if "last_date" in since
            else self._start - timedelta(days=1)
        )
        pending = weekdays_between(last, last_completed_session_date(now))
        days = pending[: self._max_days]
        self.caught_up = len(pending) <= self._max_days
        payloads = []
        for day in days:
            response = await self._client.get(
                GROUPED_URL.format(day=day.isoformat()), params={"adjusted": "false"}
            )
            if not response.json().get("resultsCount"):
                continue  # weekend or holiday
            close = datetime.combine(day, time(16, 0), tzinfo=NY)
            payloads.append(
                RawPayload(
                    source_id=f"grouped-{day.isoformat()}",
                    ext="json.gz",
                    body=gzip.compress(response.content),
                    fetched_at=now,
                    url=GROUPED_URL.format(day=day.isoformat()),
                    published_at=close,
                    kind=KIND_GROUPED,
                )
            )
        return payloads, ({"last_date": days[-1].isoformat()} if days else since)

    def parse(self, raw: RawPayload) -> list[MassiveRecord]:
        records: list[MassiveRecord] = []
        for r in _body(raw).get("results", []):
            if not all(k in r for k in ("T", "o", "h", "l", "c", "v", "t")):
                continue
            records.append(
                PriceBar(
                    ticker=str(r["T"]).upper(),
                    ts=datetime.fromtimestamp(r["t"] / 1000, UTC),
                    open=Decimal(str(r["o"])),
                    high=Decimal(str(r["h"])),
                    low=Decimal(str(r["l"])),
                    close=Decimal(str(r["c"])),
                    volume=Decimal(str(r["v"])),
                    vwap=Decimal(str(r["vw"])) if "vw" in r else None,
                )
            )
        return records

    def upsert(self, conn: Connection, stored: StoredPayload, records: list[MassiveRecord]) -> None:
        bars = [r for r in records if isinstance(r, PriceBar)]
        if not bars:
            return
        # Only tickers with an entity are stored. known_at is the close: the bar is public then.
        conn.execute(
            text(
                """
                INSERT INTO price_bar
                    (security_id, ticker, ts, o, h, l, c, v, vwap, source, known_at)
                SELECT DISTINCT ON (a.entity_id, p.ticker, p.ts)
                       a.entity_id, p.ticker, p.ts, p.o, p.h, p.l, p.c, p.v, p.vwap, 'massive', p.ts
                FROM unnest(
                    CAST(:ticker AS text[]), CAST(:ts AS timestamptz[]), CAST(:o AS numeric[]),
                    CAST(:h AS numeric[]), CAST(:l AS numeric[]), CAST(:c AS numeric[]),
                    CAST(:v AS numeric[]), CAST(:vwap AS numeric[])
                ) AS p(ticker, ts, o, h, l, c, v, vwap)
                JOIN entity_alias a
                  ON a.kind = 'ticker' AND a.alias = p.ticker AND a.valid_to IS NULL
                ON CONFLICT (security_id, ticker, ts) DO NOTHING
                """
            ),
            {
                "ticker": [b.ticker for b in bars],
                "ts": [b.ts for b in bars],
                "o": [b.open for b in bars],
                "h": [b.high for b in bars],
                "l": [b.low for b in bars],
                "c": [b.close for b in bars],
                "v": [b.volume for b in bars],
                "vwap": [b.vwap for b in bars],
            },
        )


class MassiveActionsConnector(BaseConnector[MassiveRecord]):
    name = "massive_actions"
    schedule = "batch"

    def __init__(
        self, client: Any, start: date, now: datetime | None = None, page_limit: int = 5000
    ) -> None:
        self._client = client
        self._start = start
        self._now = now
        self._limit = page_limit

    @classmethod
    def from_settings(cls, settings: Settings, start: date) -> "MassiveActionsConnector":
        return cls(massive_client(settings.massive_api_key.get_secret_value()), start)

    async def _pages(self, url: str, params: dict[str, Any]) -> list[bytes]:
        pages: list[bytes] = []
        next_url: str | None = None
        while True:
            response = await (
                self._client.get(next_url) if next_url else self._client.get(url, params=params)
            )
            pages.append(response.content)
            next_url = response.json().get("next_url")
            if not next_url:
                return pages

    async def fetch(self, since: Cursor) -> tuple[list[RawPayload], Cursor]:
        now = self._now or datetime.now(UTC)
        floor = (
            date.fromisoformat(since["from"]) - ACTIONS_OVERLAP if "from" in since else self._start
        )
        floor = max(floor, self._start)
        payloads = []
        for kind, url, date_param, sort in (
            (KIND_DIVIDENDS, DIVIDENDS_URL, "ex_dividend_date.gte", "ex_dividend_date.asc"),
            (KIND_SPLITS, SPLITS_URL, "execution_date.gte", "execution_date.asc"),
        ):
            params = {date_param: floor.isoformat(), "limit": self._limit, "sort": sort}
            for i, page in enumerate(await self._pages(url, params)):
                digest = hashlib.sha256(page).hexdigest()[:12]
                payloads.append(
                    RawPayload(
                        source_id=f"{kind}-{now:%Y-%m-%d}-p{i}-{digest}",
                        ext="json",
                        body=page,
                        fetched_at=now,
                        url=url,
                        published_at=now,
                        kind=kind,
                    )
                )
        return payloads, {"from": last_completed_session_date(now).isoformat()}

    def parse(self, raw: RawPayload) -> list[MassiveRecord]:
        records: list[MassiveRecord] = []
        for r in _body(raw).get("results", []):
            if raw.kind == KIND_DIVIDENDS:
                if r.get("cash_amount") is None or not r.get("ex_dividend_date"):
                    continue
                records.append(
                    Dividend(
                        ticker=str(r["ticker"]).upper(),
                        ex_date=date.fromisoformat(r["ex_dividend_date"]),
                        cash_amount=Decimal(str(r["cash_amount"])),
                        currency=r.get("currency"),
                        declared_at=_opt_date(r.get("declaration_date")),
                        pay_date=_opt_date(r.get("pay_date")),
                        source_id=r["id"],
                    )
                )
            elif raw.kind == KIND_SPLITS:
                if not r.get("split_from") or not r.get("split_to") or not r.get("execution_date"):
                    continue
                records.append(
                    Split(
                        ticker=str(r["ticker"]).upper(),
                        ex_date=date.fromisoformat(r["execution_date"]),
                        split_from=Decimal(str(r["split_from"])),
                        split_to=Decimal(str(r["split_to"])),
                        source_id=r["id"],
                    )
                )
            else:
                raise ValueError(f"unknown payload kind {raw.kind!r}")
        return records

    def upsert(self, conn: Connection, stored: StoredPayload, records: list[MassiveRecord]) -> None:
        rows = []
        for r in records:
            if isinstance(r, Dividend):
                # A dividend is knowable from its declaration; fall back to the ex date.
                known = (r.declared_at or r.ex_date) + timedelta(days=1)  # announced during the day
                rows.append(
                    {
                        "ticker": r.ticker,
                        "kind": "dividend",
                        "ex": r.ex_date,
                        "sf": None,
                        "st": None,
                        "cash": r.cash_amount,
                        "cur": r.currency,
                        "decl": r.declared_at,
                        "pay": r.pay_date,
                        "sid": r.source_id,
                        "known": datetime.combine(known, time(0, 0), tzinfo=NY),
                        "doc": stored.doc_id,
                    }
                )
            elif isinstance(r, Split):
                # The API gives no announcement date; use the ex date (conservative).
                rows.append(
                    {
                        "ticker": r.ticker,
                        "kind": "split",
                        "ex": r.ex_date,
                        "sf": r.split_from,
                        "st": r.split_to,
                        "cash": None,
                        "cur": None,
                        "decl": None,
                        "pay": None,
                        "sid": r.source_id,
                        "known": datetime.combine(r.ex_date, time(0, 0), tzinfo=NY),
                        "doc": stored.doc_id,
                    }
                )
        if not rows:
            return
        conn.execute(
            text(
                """
                INSERT INTO corporate_action
                    (security_id, ticker, kind, ex_date, split_from, split_to, cash_amount,
                     currency, declared_at, pay_date, source, source_id, known_at, doc_id)
                SELECT a.entity_id, :ticker, :kind, :ex, :sf, :st, :cash, :cur, :decl, :pay,
                       'massive', :sid, :known, :doc
                FROM entity_alias a
                WHERE a.kind = 'ticker' AND a.alias = :ticker AND a.valid_to IS NULL
                LIMIT 1
                ON CONFLICT (source, source_id) DO NOTHING
                """
            ),
            rows,
        )


def _opt_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
