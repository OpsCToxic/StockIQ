from datetime import UTC, datetime
from pathlib import Path

from stockiq.connectors.base import RawPayload
from stockiq.connectors.sec_tickers.connector import (
    KIND_COMPANY,
    KIND_FUND,
    SecTickersConnector,
)
from stockiq.connectors.sec_tickers.models import SecCompany, SecFund

FIXTURES = Path(__file__).parents[2] / "fixtures" / "sec_tickers"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _raw(filename: str, kind: str) -> RawPayload:
    return RawPayload(
        source_id=f"{kind}-2026-11-07",
        ext="json",
        body=(FIXTURES / filename).read_bytes(),
        fetched_at=NOW,
        published_at=NOW,
        kind=kind,
    )


def test_parse_companies_pads_cik_and_uppercases() -> None:
    records = SecTickersConnector(client=None).parse(
        _raw("company_tickers_exchange.json", KIND_COMPANY)
    )
    assert all(isinstance(r, SecCompany) for r in records)
    apple = next(r for r in records if isinstance(r, SecCompany) and r.ticker == "AAPL")
    assert apple.cik == "0000320193"
    assert apple.exchange == "Nasdaq"
    assert len(records) == 7


def test_parse_funds_keeps_series_and_filer() -> None:
    records = SecTickersConnector(client=None).parse(_raw("company_tickers_mf.json", KIND_FUND))
    voo = next(r for r in records if isinstance(r, SecFund) and r.ticker == "VOO")
    assert voo.series_id == "S000002839"
    assert voo.filer_cik == "0000036405"
