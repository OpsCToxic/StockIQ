from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from xml.etree.ElementTree import fromstring

from stockiq.connectors.nport.connector import NS, _parse_swap, parse_report

FIX = Path(__file__).parents[2] / "fixtures" / "nport"
KNOWN = datetime(2026, 10, 1, tzinfo=UTC)


def _swap_el(recv: str, pay: str, ref: str = "TSLA", notional: str = "100") -> object:
    xml = f"""<invstOrSec xmlns="{NS[1:-1]}"><derivativeInfo><swapDeriv>
      <descRefInstrmnt><indexBasketInfo><indexName>N/A</indexName>
        <indexIdentifier>{ref}</indexIdentifier></indexBasketInfo></descRefInstrmnt>
      <floatingRecDesc fixedOrFloating="Floating" floatingRtIndex="{recv}"/>
      <floatingPmntDesc fixedOrFloating="Floating" floatingRtIndex="{pay}"/>
      <notionalAmt>{notional}</notionalAmt></swapDeriv></derivativeInfo></invstOrSec>"""
    return fromstring(xml)


def test_real_tsll_filing_has_seven_long_swaps_on_tsla() -> None:
    report = parse_report((FIX / "nport_tsll.xml").read_bytes(), "acc", KNOWN)
    swaps = [h for h in report.holdings if h.swap_ref]
    assert len(swaps) == 7
    assert {h.swap_ref for h in swaps} == {"TSLA"}
    assert {h.swap_direction for h in swaps} == {"long"}
    assert sum((h.notional or Decimal(0)) for h in swaps) == Decimal("5591981553.15")
    assert report.net_assets == Decimal("3034816690.84")
    assert report.series_id == "S000072483"


def test_swap_fields_come_from_the_swap_not_the_equity_lines() -> None:
    report = parse_report((FIX / "nport_tsll.xml").read_bytes(), "acc", KNOWN)
    equities = [h for h in report.holdings if h.asset_cat == "EC"]
    assert equities and all(h.swap_ref is None and h.notional is None for h in equities)


def test_receiving_the_rate_leg_means_short_exposure() -> None:
    long_ = _swap_el("Total Return on Tesla Inc", "1 month SOFR + spread")
    short = _swap_el("1 month SOFR", "Total Return Swap Contract of Tesla Inc")
    assert _parse_swap(long_)[2] == "long"  # type: ignore[arg-type]
    assert _parse_swap(short)[2] == "short"  # type: ignore[arg-type]


def test_unparseable_swaps_are_skipped_not_guessed() -> None:
    assert _parse_swap(_swap_el("x", "y", ref="N/A")) == (None, None, None)  # type: ignore[arg-type]
    plain = fromstring(f'<invstOrSec xmlns="{NS[1:-1]}"><name>x</name></invstOrSec>')
    assert _parse_swap(plain) == (None, None, None)
