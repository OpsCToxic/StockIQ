"""Concentration flags and the Herfindahl index over a look-through exposure.

Pure functions of an `Exposure` (already point-in-time: it was built for one `as_of`). Nothing here
reads the clock or the database. When the signal table exists (Phase 4) a runner will turn these
results into rows; until then they feed the report.

Two bases are reported, because they answer different questions:
  funded    the value you hold, looked through (companies add up to at most your portfolio)
  economic  funded plus swap exposure (leveraged funds); can exceed 100% of your money

A flag is a node (company, SIC industry, country) whose share of your portfolio is at or above the
threshold. Buckets that are not a single node (cash, "not looked through", unknowns) are never
flagged. These describe what you hold today; they say nothing about what will happen.
"""

from dataclasses import dataclass
from decimal import Decimal

from stockiq.graph.exposure import Exposure

DEFAULT_THRESHOLD = Decimal("0.10")
_NOT_A_NODE = ("Not looked through", "Cash", "Unclassified", "Unknown", "Not equity")


@dataclass(frozen=True)
class Flag:
    kind: str  # "company" | "industry" | "country"
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


def _flags(
    kind: str,
    basis: str,
    values: dict[str, Decimal],
    total_value: Decimal,
    threshold: Decimal,
) -> list[Flag]:
    if not total_value:
        return []
    out = []
    for name, value in values.items():
        if name.startswith(_NOT_A_NODE) or value <= 0:
            continue
        share = value / total_value
        if share >= threshold:
            out.append(Flag(kind, basis, name, value, share, threshold))
    return out


def concentration(x: Exposure, threshold: Decimal = DEFAULT_THRESHOLD) -> Concentration:
    funded_named = {x.names[i]: v for i, v in x.by_company.items()}
    economic_named = {x.names[i]: v for i, v in x.economic_by_company.items()}
    flags = (
        _flags("company", "funded", funded_named, x.total_value, threshold)
        + _flags("company", "economic", economic_named, x.total_value, threshold)
        + _flags("industry", "funded", x.by_sector, x.total_value, threshold)
        + _flags("country", "funded", x.by_country, x.total_value, threshold)
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
