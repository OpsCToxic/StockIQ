from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from stockiq.connectors.nport.connector import parse_feed, parse_report
from stockiq.entities.names import normalize_name

FIX = Path(__file__).parents[2] / "fixtures" / "nport"
KNOWN = datetime(2026, 8, 29, tzinfo=UTC)


def test_parse_report_header_and_holdings() -> None:
    report = parse_report(
        (FIX / "nport_voo_trimmed.xml").read_bytes(), "0000036405-26-000473", KNOWN
    )
    assert report.series_id == "S000002839"
    assert report.series_name == "VANGUARD 500 INDEX FUND"
    assert report.report_date == date(2026, 6, 30)
    # Never earlier than report date + 60 days (2026-06-30 + 60d = 2026-08-29 midnight New York),
    # even if the filing date is earlier.
    assert report.known_at == datetime(2026, 8, 29, 4, 0, tzinfo=UTC)
    assert len(report.holdings) == 10
    first = report.holdings[0]
    assert (first.name, first.cusip, first.asset_cat) == (
        "United Airlines Holdings Inc",
        "910047109",
        "EC",
    )
    assert first.isin == "US9100471096"
    assert first.pct_val == Decimal("0.068432200489")


def test_evidence_span_is_the_filed_xml_verbatim() -> None:
    body = (FIX / "nport_voo_trimmed.xml").read_bytes()
    for h in parse_report(body, "x", KNOWN).holdings:
        assert h.span_text.startswith("<invstOrSec>") and h.span_text.endswith("</invstOrSec>")
        assert h.span_text in body.decode()
        assert h.name in h.span_text


def test_parse_feed_newest_first() -> None:
    filings = parse_feed((FIX / "series_atom_voo.xml").read_bytes())
    assert filings[0]["accession"] == "0000036405-26-000473"
    assert filings[0]["filed"] == date(2026, 8, 28)
    assert filings[0]["folder"].endswith("/000003640526000473")
    assert [f["filed"] for f in filings] == sorted((f["filed"] for f in filings), reverse=True)


def test_normalize_name() -> None:
    assert normalize_name("Apple Inc.") == normalize_name("APPLE INC") == "apple"
    assert normalize_name("MICROSOFT CORP") == normalize_name("Microsoft Corporation")
    assert normalize_name("The Coca-Cola Company") == "coca cola"
    assert normalize_name("Procter & Gamble Co") == "procter and gamble"
    assert normalize_name("Inc") == "inc"  # never normalises to nothing


def test_normalize_name_handles_filing_tags() -> None:
    sec = normalize_name("APPLIED MATERIALS INC /DE/")
    assert sec == normalize_name("Applied Materials Inc") == "applied materials"
    assert normalize_name("COSTCO WHOLESALE CORP /NEW") == normalize_name("Costco Wholesale Corp")
    assert normalize_name("Home Depot Inc/The") == normalize_name("HOME DEPOT, INC.")
    assert normalize_name("Coca-Cola Co/The") == normalize_name("COCA COLA CO")
    assert normalize_name("McDonald's Corp") == normalize_name("MCDONALDS CORP") == "mcdonalds"
    assert normalize_name("Novo Nordisk A/S") == "novo nordisk a s"  # inner slash is kept


def test_known_at_is_never_before_the_public_release_window() -> None:
    body = (FIX / "nport_voo_trimmed.xml").read_bytes()
    early = datetime(2026, 7, 28, tzinfo=UTC)  # filed 28 days after the report date
    assert parse_report(body, "x", early).known_at == datetime(2026, 8, 29, 4, 0, tzinfo=UTC)
    late = datetime(2026, 10, 1, tzinfo=UTC)  # filed after the window: the filing date wins
    assert parse_report(body, "x", late).known_at == late
