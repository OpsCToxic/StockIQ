import asyncio
import gzip
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from stockiq.connectors.base import RawPayload
from stockiq.connectors.massive.connector import (
    KIND_DIVIDENDS,
    KIND_GROUPED,
    KIND_SPLITS,
    MassiveActionsConnector,
    MassivePricesConnector,
    last_completed_session_date,
    weekdays_between,
)
from stockiq.connectors.massive.models import Dividend, PriceBar, Split

FIX = Path(__file__).parents[2] / "fixtures" / "massive"
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)  # Monday morning in New York


def _raw(name: str, kind: str, compress: bool = False) -> RawPayload:
    body = (FIX / name).read_bytes()
    return RawPayload("x", "json", gzip.compress(body) if compress else body, NOW, kind=kind)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.content = json.dumps(payload).encode()

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeClient:
    def __init__(self, by_day: dict[str, dict[str, Any]]) -> None:
        self.by_day = by_day
        self.urls: list[str] = []

    async def get(self, url: str, **_: Any) -> FakeResponse:
        self.urls.append(url)
        return FakeResponse(self.by_day.get(url.rsplit("/", 1)[-1], {"resultsCount": 0}))


def test_parse_grouped_daily_handles_plain_and_gzip() -> None:
    connector = MassivePricesConnector(None, date(2026, 11, 2))
    for compress in (False, True):
        records = connector.parse(_raw("grouped_2026-11-06.json", KIND_GROUPED, compress))
        bars = {r.ticker: r for r in records if isinstance(r, PriceBar)}
        assert len(bars) == 4
        assert bars["AAPL"].ts == datetime(2026, 11, 6, 21, 0, tzinfo=UTC)  # 4 PM ET close
        assert bars["AAPL"].volume == Decimal("1000000.5")  # fractional volume survives
        assert bars["AAPL"].close == Decimal("201.25")


def test_parse_dividends_and_splits() -> None:
    actions = MassiveActionsConnector(None, date(2026, 1, 1))
    parsed = actions.parse(_raw("dividends.json", KIND_DIVIDENDS))
    divs = [r for r in parsed if isinstance(r, Dividend)]
    assert divs[0].cash_amount == Decimal("0.27") and divs[0].declared_at == date(2026, 10, 28)
    assert divs[1].declared_at is None  # optional fields stay optional
    (split,) = [r for r in actions.parse(_raw("splits.json", KIND_SPLITS)) if isinstance(r, Split)]
    assert (split.split_from, split.split_to) == (1, 4)


def test_weekdays_skip_weekends() -> None:
    days = weekdays_between(date(2026, 11, 5), date(2026, 11, 10))  # after Thu, through Tue
    assert [d.isoformat() for d in days] == ["2026-11-06", "2026-11-09", "2026-11-10"]


def test_never_asks_for_today() -> None:
    # Monday 10 AM ET: the last completed date is Sunday, which weekdays_between then drops.
    assert last_completed_session_date(NOW) == date(2026, 11, 8)


def test_fetch_skips_empty_days_and_advances_cursor() -> None:
    grouped = json.loads((FIX / "grouped_2026-11-06.json").read_text())
    client = FakeClient({"2026-11-06": grouped})
    connector = MassivePricesConnector(client, date(2026, 11, 5), max_days=20, now=NOW)
    payloads, cursor = asyncio.run(connector.fetch({}))
    assert [p.source_id for p in payloads] == ["grouped-2026-11-06"]
    assert cursor == {"last_date": "2026-11-06"}
    assert connector.caught_up
    assert all("apiKey" not in u for u in client.urls)


def test_fetch_chunks_long_backfills() -> None:
    client = FakeClient({})
    connector = MassivePricesConnector(client, date(2026, 10, 1), max_days=5, now=NOW)
    _, cursor = asyncio.run(connector.fetch({}))
    assert cursor == {"last_date": "2026-10-07"}
    assert not connector.caught_up
