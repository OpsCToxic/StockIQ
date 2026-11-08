from datetime import UTC, datetime
from decimal import Decimal

from stockiq.graph.exposure import BreakdownPart, Exposure
from stockiq.modules.exposure.concentration import concentration, herfindahl


def D(x: str) -> Decimal:
    return Decimal(x)


def _exposure(funded: dict[int, str], synthetic: dict[int, str] | None = None) -> Exposure:
    x = Exposure(as_of=datetime(2026, 11, 8, tzinfo=UTC))
    x.names = {i: f"Co{i}" for i in {*funded, *(synthetic or {})}}
    x.by_company = {i: D(v) for i, v in funded.items()}
    x.synthetic_by_company = {i: D(v) for i, v in (synthetic or {}).items()}
    x.total_value = D("1000")
    return x


def test_herfindahl_of_equal_companies_is_one_over_n() -> None:
    h = herfindahl("funded", {i: D("100") for i in range(4)}, D("1000"))
    assert h.hhi == D("0.25") and h.effective_n == D("4") and h.companies == 4
    assert h.covered_fraction == D("0.4")


def test_one_company_is_a_herfindahl_of_one() -> None:
    h = herfindahl("funded", {1: D("500")}, D("1000"))
    assert h.hhi == 1 and h.effective_n == 1


def test_an_empty_exposure_has_no_herfindahl() -> None:
    h = herfindahl("funded", {}, D("1000"))
    assert (h.hhi, h.companies, h.covered_fraction) == (0, 0, 0)


def test_flags_use_the_threshold_inclusively_and_sort_largest_first() -> None:
    c = concentration(_exposure({1: "100", 2: "250", 3: "99"}))
    funded = [f for f in c.flags if f.kind == "company" and f.basis == "funded"]
    assert [f.name for f in funded] == ["Co2", "Co1"]  # 25% and exactly 10%; 9.9% is not flagged
    assert [f.share for f in funded] == [D("0.25"), D("0.1")]


def test_swaps_show_up_as_economic_exposure_beyond_the_funded_value() -> None:
    # $200 held directly in company 1, plus $1,800 of swap exposure: 200% of a $1,000 portfolio.
    c = concentration(_exposure({1: "200"}, {1: "1800"}))
    econ = next(f for f in c.flags if f.basis == "economic")
    assert econ.share == D("2.0")
    funded = next(f for f in c.flags if f.basis == "funded" and f.kind == "company")
    assert funded.share == D("0.2")


def test_buckets_that_are_not_a_single_node_are_never_flagged() -> None:
    x = _exposure({1: "50"})
    x.by_sector = {
        "Cash, collateral and other (not companies)": D("600"),
        "Cash": D("200"),
        "Unclassified": D("150"),
    }
    x.by_country = {"Unknown (direct holding)": D("700"), "Not equity / not reported": D("200")}
    assert concentration(x).flags == []


def test_a_real_node_in_the_industry_view_is_flagged() -> None:
    x = _exposure({1: "50"})
    x.by_sector = {"SIC 3711 Motor Vehicles": D("300"), "Cash": D("200")}
    flags = concentration(x).flags
    assert [(f.kind, f.name) for f in flags] == [("industry", "SIC 3711 Motor Vehicles")]


def test_a_zero_portfolio_flags_nothing() -> None:
    x = _exposure({1: "50"})
    x.total_value = D("0")
    assert concentration(x).flags == []


def test_a_company_whose_name_starts_like_a_bucket_is_still_flagged() -> None:
    x = _exposure({1: "300"})
    x.names[1] = "Cash America International"  # not the Cash bucket
    flags = [f for f in concentration(x).flags if f.kind == "company" and f.basis == "funded"]
    assert [f.name for f in flags] == ["Cash America International"]


def test_two_companies_with_the_same_name_are_not_merged_or_overwritten() -> None:
    x = _exposure({1: "150", 2: "150"})
    x.names[1] = x.names[2] = "Acme"
    flags = [f for f in concentration(x).flags if f.kind == "company" and f.basis == "funded"]
    assert len(flags) == 2 and sum(f.value for f in flags) == D("300")


def _part(bucket: str, value: str) -> BreakdownPart:
    return BreakdownPart(1, "FND", "Fund", bucket, bucket, D(value), D("0.5"), 3)


def test_a_large_share_of_filed_equity_we_could_not_match_gets_a_coverage_flag() -> None:
    x = _exposure({1: "50"})
    x.breakdown = [_part("unmatched_equity", "600")]
    cov = [f for f in concentration(x).flags if f.kind == "coverage"]
    assert len(cov) == 1 and cov[0].share == D("0.6")
    x.breakdown = [_part("unmatched_equity", "50")]
    assert [f for f in concentration(x).flags if f.kind == "coverage"] == []


def test_cash_and_collateral_are_not_a_coverage_gap() -> None:
    """TSLL's money-market collateral is not company exposure; it must not read as unexamined."""
    x = _exposure({1: "50"})
    x.breakdown = [_part("cash", "900"), _part("derivatives", "-300")]
    assert [f for f in concentration(x).flags if f.kind == "coverage"] == []
