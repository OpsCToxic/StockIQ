"""Concentration flags and the Herfindahl index over a look-through exposure.

Pure functions of an `Exposure` (already point-in-time: it was built for one `as_of`). Nothing here
reads the clock or the database. When the signal table exists (Phase 4) a runner will turn these
results into rows; until then they feed the report.

Two bases are reported, because they answer different questions:
  funded    the value you hold, looked through (companies add up to at most your portfolio)
  economic  funded plus swap exposure (leveraged funds); can exceed 100% of your money

A flag is a node (company, SIC industry, country) whose share of your portfolio is at or above the
threshold. Buckets that are not a single node (cash, "not looked through", unknowns) are never
flagged as a node; a large not-looked-through share gets its own "coverage" flag instead, because
a Herfindahl index over the covered part alone can look fine while most of the money is unexamined.
Companies are keyed by entity id, never by display name. Economic figures are gross long: a net
short swap is left out. Provisional matches (under 0.9 confidence) count at full weight.
These describe what you hold today; they say nothing about what will happen.
"""

from dataclasses import dataclass
from decimal import Decimal

from stockiq.graph.exposure import NOT_COMPANY, Exposure

DEFAULT_THRESHOLD = Decimal("0.10")
# Exact bucket labels that are not a single company, industry or country.
_BUCKETS = frozenset(
    {
        NOT_COMPANY,
        "Cash",
        "Unclassified",
        "Unknown (direct holding)",
        "Unknown (no fund filing known)",
        "Not equity / not reported",
    }
)


@dataclass(frozen=True)
class Flag:
    kind: str  # "company" | "industry" | "country" | "coverage"
    basis: str  # "funded" | "economic"
    name: str
    value: Decimal
    share: Decimal  # of the portfolio's value; economic shares can exceed 1
    threshold: Decimal


@dataclass(frozen=True)
class Herfindahl:
    """HHI over company shares of the looked-through exposure (shares sum to 1).

    1.0 means a single company; 1/n means n equal companies. `effective_n` is 1/HHI. It covers
    only the part of the portfolio that was looked through down to companies."""

    basis: str
    hhi: Decimal
    effective_n: Decimal
    companies: int
    covered_value: Decimal
    covered_fraction: Decimal  # of the portfolio's value


@dataclass(frozen=True)
class Concentration:
    herfindahl: list[Herfindahl]
    flags: list[Flag]


def herfindahl(basis: str, exposures: dict[int, Decimal], total_value: Decimal) -> Herfindahl:
    positive = {k: v for k, v in exposures.items() if v > 0}
    covered = sum(positive.values(), Decimal(0))
    if not positive:
        return Herfindahl(basis, Decimal(0), Decimal(0), 0, Decimal(0), Decimal(0))
    hhi = sum(((v / covered) ** 2 for v in positive.values()), Decimal(0))
    return Herfindahl(
        basis=basis,
        hhi=hhi,
        effective_n=1 / hhi,
        companies=len(positive),
        covered_value=covered,
        covered_fraction=covered / total_value if total_value else Decimal(0),
    )


def _company_flags(
    basis: str, values: dict[int, Decimal], x: Exposure, threshold: Decimal
) -> list[Flag]:
    if not x.total_value:
        return []
    return [
        Flag("company", basis, x.names[i], v, v / x.total_value, threshold)
        for i, v in values.items()
        if v > 0 and v / x.total_value >= threshold
    ]


def _node_flags(
    kind: str, values: dict[str, Decimal], total_value: Decimal, threshold: Decimal
) -> list[Flag]:
    if not total_value:
        return []
    return [
        Flag(kind, "funded", name, v, v / total_value, threshold)
        for name, v in values.items()
        if name not in _BUCKETS and v > 0 and v / total_value >= threshold
    ]


def concentration(x: Exposure, threshold: Decimal = DEFAULT_THRESHOLD) -> Concentration:
    flags = (
        _company_flags("funded", x.by_company, x, threshold)
        + _company_flags("economic", x.economic_by_company, x, threshold)
        + _node_flags("industry", x.by_sector, x.total_value, threshold)
        + _node_flags("country", x.by_country, x.total_value, threshold)
    )
    # Filed equity we could not tie to a company is the real gap (cash and collateral are not
    # a gap: they are not company exposure). The Herfindahl below only sees the matched part.
    gap = x.unmatched_equity_total
    if x.total_value and gap > 0 and gap / x.total_value >= threshold:
        flags.append(
            Flag(
                "coverage",
                "funded",
                "Equity not matched to a company",
                gap,
                gap / x.total_value,
                threshold,
            )
        )
    # An economic flag that only repeats a funded flag at the same name is still reported: the
    # difference between the two is the point (swaps).
    flags.sort(key=lambda f: f.share, reverse=True)
    return Concentration(
        herfindahl=[
            herfindahl("funded", x.by_company, x.total_value),
            herfindahl("economic", x.economic_by_company, x.total_value),
        ],
        flags=flags,
    )
