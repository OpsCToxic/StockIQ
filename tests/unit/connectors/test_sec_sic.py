import gzip
from datetime import UTC, datetime
from pathlib import Path

from stockiq.connectors.base import RawPayload
from stockiq.connectors.sec_sic.connector import KIND, SecSicConnector
from stockiq.graph.sic import division_for, division_for_sector_name

FIX = Path(__file__).parents[2] / "fixtures" / "sec_sic" / "submissions_aapl_trimmed.json"
NOW = datetime(2026, 11, 8, tzinfo=UTC)


def _raw(body: bytes) -> RawPayload:
    return RawPayload("s", "json.gz", gzip.compress(body), NOW, kind=KIND, url="https://x/y.json")


def test_parse_real_submissions_payload() -> None:
    (rec,) = SecSicConnector(None, []).parse(_raw(FIX.read_bytes()))
    assert (rec.cik, rec.sic, rec.description) == ("0000320193", "3571", "Electronic Computers")
    assert rec.span == '"sic":"3571","sicDescription":"Electronic Computers"'  # verbatim evidence


def test_company_without_a_sic_is_skipped_not_guessed() -> None:
    connector = SecSicConnector(None, [])
    body = b'{"cik":"1","sic":"","sicDescription":"","name":"Shell Co"}'
    assert connector.parse(_raw(body)) == []
    assert connector.skipped == ["1"]


def test_divisions() -> None:
    assert division_for(3571) == "Manufacturing"
    assert division_for(5211) == "Retail Trade"
    assert division_for(6022) == "Finance, Insurance & Real Estate"
    assert division_for(7372) == "Services"
    assert division_for(4911).startswith("Transportation")
    assert division_for(9999 + 1) == "Unclassified"
    assert (
        division_for_sector_name("SIC 3711 Motor Vehicles & Passenger Car Bodies")
        == "Manufacturing"
    )
    assert division_for_sector_name("Tesla") == "Unclassified"
