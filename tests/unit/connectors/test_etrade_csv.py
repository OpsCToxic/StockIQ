from decimal import Decimal
from pathlib import Path

import pytest

from stockiq.connectors.etrade_csv.connector import parse_export

FIXTURE = Path(__file__).parents[2] / "fixtures" / "etrade_csv" / "PortfolioDownload.csv"


def test_parse_positions_cash_and_snapshot_time() -> None:
    export = parse_export(FIXTURE.read_bytes())
    assert [p.symbol for p in export.positions] == ["AAPL", "MSFT", "VOO"]
    assert export.cash == Decimal("100.00")
    assert export.total_value == Decimal("5500.00")
    assert export.account_name == "All brokerage accounts"
    # 07:57 PM ET on Nov 7 is 00:57 UTC on Nov 8 (EST).
    assert export.generated_at.isoformat() == "2026-11-07T19:57:00-05:00"


def test_cost_basis_is_value_minus_gain_to_the_cent() -> None:
    msft = next(p for p in parse_export(FIXTURE.read_bytes()).positions if p.symbol == "MSFT")
    assert msft.cost_basis == Decimal("1521.0000")


def test_account_name_can_be_overridden() -> None:
    assert parse_export(FIXTURE.read_bytes(), "Brokerage 1").account_name == "Brokerage 1"


def test_refuses_file_that_does_not_add_up() -> None:
    bad = FIXTURE.read_text().replace(
        "TOTAL,,,,,4671.00,.00,729.00,15.61,5500.00", "TOTAL,,,,,4671.00,.00,729.00,15.61,9999.00"
    )
    with pytest.raises(ValueError, match="TOTAL"):
        parse_export(bad.encode())


def test_refuses_file_without_snapshot_time() -> None:
    no_footer = "\n".join(
        ln for ln in FIXTURE.read_text().splitlines() if not ln.startswith("Generated at")
    )
    with pytest.raises(ValueError, match="Generated at"):
        parse_export(no_footer.encode())
