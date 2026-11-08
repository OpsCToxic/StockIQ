from datetime import UTC, datetime
from decimal import Decimal

from stockiq.graph.exposure import Exposure
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
        "Not looked through (fund cash)": D("600"),
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
