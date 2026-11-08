from datetime import UTC, date, datetime
from decimal import Decimal

from stockiq.api.composition import build_exposure_bars, build_holdings
from stockiq.graph.exposure import BreakdownItem, BreakdownPart, Exposure, ExposurePath


def D(x: str) -> Decimal:
    return Decimal(x)


def item(name: str, value: str, **kw: object) -> BreakdownItem:
    base: dict[str, object] = {
        "name": name, "title": name, "your_value": D(value), "fund_value": None,
        "fund_share": None, "notional": None, "counterparty": None, "direction": None,
        "reference": None, "edge_id": None,
    }  # fmt: skip
    return BreakdownItem(**{**base, **kw})  # type: ignore[arg-type]


def part(bucket: str, value: str, items: list[BreakdownItem] | None = None, lines: int = 0):  # type: ignore[no-untyped-def]
    return BreakdownPart(
        1, "TSLL", "Direxion Fund", bucket, bucket, D(value), D("0"), lines, items or []
    )


def tsll() -> Exposure:
    """TSLL as filed, on a $9,768 holding: $1,537 of Tesla stock, $13,866 of money-market funds,
    -$5,455 of swaps in two parts, -$180 other net."""
    x = Exposure(as_of=datetime(2026, 11, 8, tzinfo=UTC))
    x.total_value = D("19885")
    x.names = {7: "Tesla, Inc."}
    x.paths = [ExposurePath(1, "TSLL", 7, D("1537"), "fund", edge_id=11, confidence=D("0.95"))]
    swaps = [
        item("TESLA INC Swap", "-3000", counterparty="Barclays Bank PLC", reference="TSLA",
             edge_id=9, notional=D("1084990406"), fund_value=D("-246894572")),
        item("TESLA INC Swap", "-2455", counterparty="BNP Paribas", reference="TSLA", edge_id=9),
    ]  # fmt: skip
    x.breakdown = [
        part(
            "cash",
            "13866",
            [item("DREYFUS", "8000", fund_value=D("1100000000")), item("GOLDMAN", "5866")],
            2,
        ),
        part("derivatives", "-5455", swaps, 2),
        part("other", "-180"),
    ]
    x.fund_report_dates = {"Direxion Fund": date(2026, 7, 31)}
    return x


def test_every_holdings_segments_add_up_to_its_value_exactly() -> None:
    (row,) = build_holdings(tsll())
    assert row.value == D("9768")
    assert sum((s.value for s in row.segments), D(0)) == row.value
    assert abs(sum((s.share for s in row.segments), D(0)) - D(1)) < D("1e-20")  # division rounding


def test_positives_come_first_and_what_the_fund_owes_comes_last() -> None:
    (row,) = build_holdings(tsll())
    kinds = [s.kind for s in row.segments]
    assert kinds == ["stock", "cash", "cash", "swap_owed", "swap_owed", "other"]
    first_negative = next(i for i, s in enumerate(row.segments) if s.value < 0)
    assert all(s.value < 0 for s in row.segments[first_negative:])


def test_each_swap_is_its_own_negative_segment_named_for_its_bank_with_evidence() -> None:
    (row,) = build_holdings(tsll())
    barclays = next(s for s in row.segments if s.label.startswith("Barclays"))
    assert barclays.kind == "swap_owed" and barclays.value == D("-3000")
    assert barclays.label == "Barclays Bank PLC: swap on TSLA" and barclays.edge_id == 9
    assert barclays.note is not None and "$1.08B" in barclays.note
    assert barclays.share == D("-3000") / D("9768")


def test_money_market_funds_are_listed_individually_largest_first() -> None:
    (row,) = build_holdings(tsll())
    cash = [s for s in row.segments if s.kind == "cash"]
    assert [s.label for s in cash] == ["DREYFUS", "GOLDMAN"]
    assert cash[0].note is not None and "$1.10B" in cash[0].note


def test_the_filing_date_is_reported_for_a_fund_and_the_stock_has_none() -> None:
    x = tsll()
    assert build_holdings(x)[0].report_as_of == date(2026, 7, 31)
    uuuu = Exposure(as_of=x.as_of)
    uuuu.total_value = D("100")
    uuuu.names = {3: "Energy Fuels"}
    uuuu.paths = [ExposurePath(2, "UUUU", 3, D("100"), "direct")]
    (stock,) = build_holdings(uuuu)
    assert stock.report_as_of is None and stock.name == "Energy Fuels"
    assert [s.label for s in stock.segments] == ["Energy Fuels"]


def test_a_fund_with_many_companies_shows_the_top_and_folds_the_rest() -> None:
    x = Exposure(as_of=datetime(2026, 11, 8, tzinfo=UTC))
    x.total_value = D("1000")
    x.names = {i: f"Co{i}" for i in range(1, 6)}
    x.paths = [ExposurePath(1, "VOO", i, D(str(100 * (6 - i))), "fund") for i in range(1, 6)]
    (row,) = build_holdings(x, top=2)
    assert [s.label for s in row.segments] == ["Co1", "Co2", "Other companies (3)"]
    assert sum((s.value for s in row.segments), D(0)) == row.value == D("1500")


def test_equity_we_could_not_match_is_its_own_segment_and_never_netted_away() -> None:
    x = tsll()
    x.breakdown = [
        BreakdownPart(1, "TSLL", "F", "unmatched_equity", "u", D("147"), D("0"), 13, []),
        part("cash", "33", [item("MM", "33")]),
        part("other", "-9"),
    ]
    (row,) = build_holdings(x)
    gap = next(s for s in row.segments if s.kind == "unmatched")
    assert gap.value == D("147") and "13 filed stock lines" in (gap.note or "")
    assert sum((s.value for s in row.segments), D(0)) == row.value


def test_futures_without_a_reference_are_folded_into_one_net_segment() -> None:
    x = tsll()
    x.breakdown = [
        part("derivatives", "-0.4", [item("FUT1", "-0.1"), item("FUT2", "-0.3")], 2),
        part("other", "-9"),
    ]
    (row,) = build_holdings(x)
    other = [s for s in row.segments if s.kind == "other"]
    assert len(other) == 1 and other[0].value == D("-9.4")


def test_a_fund_with_no_filing_known_is_one_honest_segment() -> None:
    x = tsll()
    x.paths = []
    x.breakdown = [BreakdownPart(1, "TSLL", "F", "unknown", "u", D("500"), D("1"), 0, [])]
    (row,) = build_holdings(x)
    assert [s.label for s in row.segments] == ["No fund holdings filing known yet"]
    assert row.value == D("500")


def test_provisional_company_matches_are_marked() -> None:
    x = tsll()
    x.paths = [ExposurePath(1, "TSLL", 7, D("1537"), "fund", edge_id=11, confidence=D("0.6"))]
    (row,) = build_holdings(x)
    assert row.segments[0].provisional is True and row.segments[0].note is not None


def test_exposure_bars_add_swaps_to_funded_stock_and_can_pass_one_hundred_percent() -> None:
    x = tsll()
    x.by_company = {7: D("1711")}
    x.synthetic_by_company = {7: D("17999")}
    x.paths.append(ExposurePath(1, "TSLL", 7, D("17999"), "swap", edge_id=9, confidence=D("0.95")))
    (bar,) = build_exposure_bars(x)
    assert bar.name == "Tesla, Inc." and bar.swap_edge_id == 9
    assert bar.funded == D("1711") and bar.swap == D("17999")
    assert bar.total_share == (D("1711") + D("17999")) / D("19885")
    assert bar.funded_share + bar.swap_share == bar.total_share


def test_exposure_bars_are_ranked_and_limited() -> None:
    x = Exposure(as_of=datetime(2026, 11, 8, tzinfo=UTC))
    x.total_value = D("1000")
    x.names = {i: f"Co{i}" for i in range(1, 11)}
    x.by_company = {i: D(str(i * 10)) for i in range(1, 11)}
    bars = build_exposure_bars(x, limit=3)
    assert [b.name for b in bars] == ["Co10", "Co9", "Co8"]


def test_the_other_net_note_only_mentions_futures_when_there_are_futures() -> None:
    swaps_only = tsll()  # TSLL has swaps and a net other, but no futures
    (row,) = build_holdings(swaps_only)
    other = next(s for s in row.segments if s.kind == "other")
    assert other.note == "Net of net other assets and liabilities"
    with_futures = tsll()
    with_futures.breakdown.append(part("derivatives", "-1", [item("FUT", "-1")], 1))
    (row,) = build_holdings(with_futures)
    note = next(s for s in row.segments if s.kind == "other").note or ""
    assert "futures and other derivatives" in note
