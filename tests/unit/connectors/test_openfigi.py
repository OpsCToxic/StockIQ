from datetime import UTC, datetime
from pathlib import Path

from stockiq.connectors.base import RawPayload
from stockiq.connectors.openfigi.connector import OpenFigiConnector, _query_ticker
from stockiq.connectors.openfigi.models import FigiMatch, FigiMiss

FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "openfigi" / "mapping_aapl_googl_voo_brkb_unknown.json"
)
NOW = datetime(2026, 11, 8, tzinfo=UTC)


def _raw(body: bytes) -> RawPayload:
    return RawPayload(
        source_id="figi-x", ext="json", body=body, fetched_at=NOW, kind="openfigi_mapping"
    )


def test_parse_real_payload() -> None:
    records = OpenFigiConnector(client=None, tickers=[]).parse(_raw(FIXTURE.read_bytes()))
    by_ticker = {r.ticker: r for r in records}
    assert isinstance(by_ticker["AAPL"], FigiMatch)
    assert by_ticker["AAPL"].composite_figi == "BBG000B9XRY4"
    assert isinstance(by_ticker["BRK-B"], FigiMatch)  # keeps our spelling, not BRK/B
    assert isinstance(by_ticker["ZZZZNOTREAL"], FigiMiss)
    assert by_ticker["ZZZZNOTREAL"].reason == "not_found"


def test_multiple_composites_are_ambiguous_not_guessed() -> None:
    body = (
        b'{"tickers":["XYZ"],"request":[],"response":[{"data":['
        b'{"exchCode":"US","compositeFIGI":"BBG000000001"},'
        b'{"exchCode":"US","compositeFIGI":"BBG000000002"}]}]}'
    )
    (rec,) = OpenFigiConnector(client=None, tickers=[]).parse(_raw(body))
    assert isinstance(rec, FigiMiss) and rec.reason == "ambiguous"


def test_error_response_is_a_miss() -> None:
    body = b'{"tickers":["XYZ"],"request":[],"response":[{"error":"No identifier found."}]}'
    (rec,) = OpenFigiConnector(client=None, tickers=[]).parse(_raw(body))
    assert isinstance(rec, FigiMiss)


def test_share_class_spelling() -> None:
    assert _query_ticker("BRK-B") == "BRK/B"
    assert _query_ticker("BF.B") == "BF/B"
