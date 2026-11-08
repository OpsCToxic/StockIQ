"""Look-through exposure: what your money is really in, once ETFs are opened up.

Exposure to a company is the sum over paths of holding value times fund weight: a direct holding
counts at full value, a fund position at its look-through share. Whatever a fund's data does not
cover (cash, derivatives, debt, unresolved names, or no filing at all) is reported as
"not looked through" with the reason, never dropped, so the parts always add up to the portfolio.

Point-in-time: everything is read as of `as_of`. A holdings snapshot or fund report counts only if
its `known_at <= as_of`. For each fund exactly one report version is used for both company and
country: the latest report date known by then and, within it, the latest version (an amendment
arrives later than the original). Edge `valid_to` is never used; it is set when a later report
arrives and would leak the future.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from stockiq.graph.sic import division_for_sector_name

ZERO = Decimal(0)
ONE = Decimal(1)
COVERED_CATS = ("EC", "EP")
# The label for everything a fund holds that is not a company: cash, collateral,
# derivatives, debt and net other assets. Used wherever a single bucket is needed.
NOT_COMPANY = "Cash, collateral and other (not companies)"

BUCKET_LABELS = {
    "cash": "Cash and money-market funds",
    "derivatives": "Derivatives, at fair value (can be negative)",
    "debt": "Debt",
    "unmatched_equity": "Equity not matched to a company",
    "other": "Other assets and liabilities, net",
    "unknown": "No fund holdings filing known yet",
}


def bucket_for(asset_cat: str | None, payoff: str | None, matched: bool) -> str | None:
    """Which breakdown bucket a filed line belongs to, by the filing's own asset category.
    None means the line is already counted as company exposure."""
    cat = (asset_cat or "").upper()
    if cat in COVERED_CATS:
        if payoff == "Long":
            return None if matched else "unmatched_equity"
        return "other"
    if cat in ("STIV", "RA"):  # short-term investment vehicles, repurchase agreements
        return "cash"
    if cat == "DBT" or cat.startswith("ABS") or cat == "LON":
        return "debt"
    if cat.startswith("D"):  # DE, DIR, DFE, DO ...: derivatives
        return "derivatives"
    return "other"


@dataclass
class NotLookedThrough:
    label: str
    value: Decimal
    reason: str
    holding_id: int = 0  # the held fund this remainder belongs to
    holding: str = ""  # its short label (ticker)


@dataclass
class BreakdownItem:
    """One filed line inside a breakdown part: a money-market fund, a swap, a debt holding."""

    name: str
    title: str | None
    your_value: Decimal  # dollars of your holding (fund share x the line's share of the fund)
    fund_value: Decimal | None  # the line's own value in the fund, as filed (USD)
    fund_share: Decimal | None  # of the fund's net assets
    notional: Decimal | None = None
    counterparty: str | None = None
    direction: str | None = None
    reference: str | None = None  # what a swap follows (a ticker)
    edge_id: int | None = None  # graph edge whose evidence quotes this line


@dataclass
class BreakdownPart:
    """One slice of a fund's non-company remainder, in dollars of your holding."""

    holding_id: int
    holding: str  # ticker
    fund: str
    bucket: str
    label: str
    value: Decimal  # can be negative (derivatives are at fair value)
    fund_share: Decimal  # of the fund's net assets
    lines: int  # filed lines behind it
    items: list[BreakdownItem] = field(default_factory=list)


@dataclass
class ExposurePath:
    """One flow of value from a holding to a company: a direct holding, a fund's equity line, or
    swap exposure. `edge_id` points at the graph edge whose evidence backs it (None for a direct
    holding, which comes from the imported positions file)."""

    holding_id: int
    holding: str
    company_id: int
    value: Decimal
    kind: str  # "direct" | "fund" | "swap"
    edge_id: int | None = None
    confidence: Decimal | None = None


@dataclass
class Exposure:
    as_of: datetime
    snapshot_as_of: dict[int, datetime] = field(default_factory=dict)  # per account
    total_value: Decimal = ZERO  # holdings plus cash, as the broker reported
    cash: Decimal = ZERO
    names: dict[int, str] = field(default_factory=dict)
    by_company: dict[int, Decimal] = field(default_factory=dict)  # keyed by entity id
    # Swap-based exposure on top of funded value (leveraged funds). It is not money you
    # hold, so it is kept out of by_company and out of the reconciliation.
    synthetic_by_company: dict[int, Decimal] = field(default_factory=dict)
    by_country: dict[str, Decimal] = field(default_factory=dict)
    by_sector: dict[str, Decimal] = field(default_factory=dict)  # SIC industry
    by_division: dict[str, Decimal] = field(default_factory=dict)  # SIC division
    not_looked_through: list[NotLookedThrough] = field(default_factory=list)
    breakdown: list[BreakdownPart] = field(default_factory=list)
    fund_report_dates: dict[str, date] = field(default_factory=dict)
    paths: list[ExposurePath] = field(default_factory=list)

    @property
    def company_total(self) -> Decimal:
        return sum(self.by_company.values(), ZERO)

    @property
    def unlooked_total(self) -> Decimal:
        return sum((n.value for n in self.not_looked_through), ZERO)

    @property
    def unmatched_equity_total(self) -> Decimal:
        """Equity lines the filing reports but we could not tie to a company: the real gap."""
        return sum((p.value for p in self.breakdown if p.bucket == "unmatched_equity"), ZERO)

    @property
    def country_total(self) -> Decimal:
        return sum(self.by_country.values(), ZERO)

    @property
    def reconciles_to(self) -> Decimal:
        """Companies + not looked through + cash. Equals total_value if nothing was dropped."""
        return self.company_total + self.unlooked_total + self.cash

    @property
    def covered_fraction(self) -> Decimal:
        return self.company_total / self.total_value if self.total_value else ZERO

    @property
    def economic_by_company(self) -> dict[int, Decimal]:
        """Funded look-through plus swap exposure: what your money is really riding on."""
        out = dict(self.by_company)
        for entity_id, v in self.synthetic_by_company.items():
            out[entity_id] = out.get(entity_id, ZERO) + v
        return out

    def company_values_by_name(self) -> dict[str, Decimal]:
        return {self.names[i]: v for i, v in self.by_company.items()}


def look_through(conn: Connection, as_of: datetime, account_id: int | None = None) -> Exposure:
    result = Exposure(as_of=as_of)
    # A snapshot exists for an account if either holdings or cash were imported, so selling
    # everything to cash still counts as the latest snapshot.
    snapshots = conn.execute(
        text(
            """
            SELECT account_id, max(as_of) AS snap FROM (
                SELECT account_id, as_of FROM holding WHERE known_at <= :t
                UNION ALL
                SELECT account_id, as_of FROM cash_balance WHERE known_at <= :t
            ) s
            WHERE as_of <= :t AND (CAST(:a AS bigint) IS NULL OR account_id = :a)
            GROUP BY account_id
            """
        ),
        {"t": as_of, "a": account_id},
    ).all()
    for acct in snapshots:
        result.snapshot_as_of[acct.account_id] = acct.snap
        positions = conn.execute(
            text(
                """
                SELECT h.security_id, e.name, e.type, e.country, h.ticker, h.market_value
                FROM holding h JOIN entity e ON e.id = h.security_id
                WHERE h.account_id = :a AND h.as_of = :snap AND h.known_at <= :t
                """
            ),
            {"a": acct.account_id, "snap": acct.snap, "t": as_of},
        ).all()
        cash = conn.execute(
            text(
                "SELECT amount FROM cash_balance "
                "WHERE account_id = :a AND as_of = :snap AND known_at <= :t"
            ),
            {"a": acct.account_id, "snap": acct.snap, "t": as_of},
        ).scalar_one_or_none()
        result.cash += cash or ZERO
        result.total_value += cash or ZERO
        for p in positions:
            if p.market_value is None:
                raise ValueError(
                    f"{p.ticker or p.name} has no broker market value; re-import the positions CSV"
                )
            result.total_value += p.market_value
            label = p.ticker or p.name
            if p.type == "fund":
                _add_fund(conn, result, p.security_id, p.name, label, p.market_value, as_of)
            else:
                result.names[p.security_id] = p.name
                result.paths.append(
                    ExposurePath(p.security_id, label, p.security_id, p.market_value, "direct")
                )
                _add(result.by_company, p.security_id, p.market_value)
                _add(result.by_country, p.country or "Unknown (direct holding)", p.market_value)
    if result.cash:
        result.by_country["Cash"] = result.cash  # so countries add up to the portfolio too
    _sector_rollup(conn, result, as_of)
    return result


def _sector_rollup(conn: Connection, out: Exposure, as_of: datetime) -> None:
    """Funded company exposure by SIC industry and division, using classifications known
    by as_of. Unclassified, not-looked-through and cash get their own lines."""
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (e.src_id) e.src_id, s.name FROM edge e
            JOIN entity s ON s.id = e.dst_id
            WHERE e.type = 'IN_SECTOR' AND e.src_id = ANY(:ids) AND e.known_at <= :t
            ORDER BY e.src_id, e.known_at DESC
            """
        ),
        {"ids": list(out.by_company), "t": as_of},
    ).all()
    sector_of = {r.src_id: r.name for r in rows}
    for entity_id, v in out.by_company.items():
        name = sector_of.get(entity_id, "Unclassified")
        _add(out.by_sector, name, v)
        _add(out.by_division, division_for_sector_name(name), v)
    for bucket in (out.by_sector, out.by_division):
        if out.unlooked_total:
            bucket[NOT_COMPANY] = out.unlooked_total
        if out.cash:
            bucket["Cash"] = out.cash


def _add[K](bucket: dict[K, Decimal], key: K, value: Decimal) -> None:
    bucket[key] = bucket.get(key, ZERO) + value


def _breakdown(
    conn: Connection,
    out: Exposure,
    fund_id: int,
    name: str,
    label: str,
    value: Decimal,
    rest: Decimal,
    report: Any,
) -> None:
    """Split the fund's non-company remainder by the filing's own asset categories, so the
    parts add up to `rest` exactly, and keep each filed line (a money-market fund, a swap) so it
    can be shown."""
    lines = conn.execute(
        text(
            """
            SELECT asset_cat, payoff_profile, (constituent_id IS NOT NULL) AS matched,
                   constituent_id, name, title, pct_val, val_usd, swap_ref, notional,
                   counterparty, swap_direction
            FROM fund_holding
            WHERE fund_id = :f AND as_of = :rd AND known_at = :k
            ORDER BY abs(coalesce(pct_val, 0)) DESC, seq
            """
        ),
        {"f": fund_id, "rd": report.as_of, "k": report.known_at},
    ).all()
    # A swap line is backed by the fund's SYNTHETIC edge to the company it follows.
    report_start = datetime.combine(report.as_of, time(0, 0), tzinfo=UTC)
    synthetic_edge = {
        r.dst_id: r.id
        for r in conn.execute(
            text(
                "SELECT id, dst_id FROM edge WHERE src_id = :f AND type = 'SYNTHETIC' "
                "AND valid_from = :rdt AND known_at = :k"
            ),
            {"f": fund_id, "rdt": report_start, "k": report.known_at},
        ).all()
    }
    values: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    items: dict[str, list[BreakdownItem]] = {}
    for r in lines:
        bucket = bucket_for(r.asset_cat, r.payoff_profile, r.matched)
        if bucket is None:
            continue
        share = (r.pct_val or ZERO) / 100
        values[bucket] = values.get(bucket, ZERO) + value * share
        counts[bucket] = counts.get(bucket, 0) + 1
        filed_name = (r.name or "").strip()
        items.setdefault(bucket, []).append(
            BreakdownItem(
                name=r.title if filed_name.upper() in ("", "N/A") and r.title else filed_name,
                title=r.title,
                your_value=value * share,
                fund_value=r.val_usd,
                fund_share=share if r.pct_val is not None else None,
                notional=r.notional,
                counterparty=r.counterparty,
                direction=r.swap_direction,
                reference=r.swap_ref,
                edge_id=synthetic_edge.get(r.constituent_id) if r.swap_ref else None,
            )
        )
    # Net other assets and liabilities, and rounding, are not filed as lines: they are the
    # difference between the remainder and the lines, kept so the parts add up.
    residual = rest - sum(values.values(), ZERO)
    if abs(residual) > Decimal("0.005"):
        values["other"] = values.get("other", ZERO) + residual
    for bucket, v in sorted(values.items(), key=lambda kv: abs(kv[1]), reverse=True):
        out.breakdown.append(
            BreakdownPart(
                fund_id,
                label,
                name,
                bucket,
                BUCKET_LABELS[bucket],
                v,
                v / value if value else ZERO,
                counts.get(bucket, 0),
                items.get(bucket, []),
            )
        )


def _add_fund(
    conn: Connection,
    out: Exposure,
    fund_id: int,
    name: str,
    label: str,
    value: Decimal,
    as_of: datetime,
) -> None:
    # One report version per fund, chosen once and used for companies and countries alike.
    report = conn.execute(
        text(
            """
            SELECT as_of, known_at FROM fund_holding
            WHERE fund_id = :f AND known_at <= :t
            ORDER BY as_of DESC, known_at DESC LIMIT 1
            """
        ),
        {"f": fund_id, "t": as_of},
    ).first()
    if report is None:
        out.not_looked_through.append(
            NotLookedThrough(name, value, "no fund holdings filing known yet", fund_id, label)
        )
        out.breakdown.append(
            BreakdownPart(fund_id, label, name, "unknown", BUCKET_LABELS["unknown"], value, ONE, 0)
        )
        out.by_country["Unknown (no fund filing known)"] = (
            out.by_country.get("Unknown (no fund filing known)", ZERO) + value
        )
        return
    out.fund_report_dates[name] = report.as_of
    # Edges store the report date as UTC midnight; pass exactly that rather than casting a date,
    # which would depend on the database session's time zone.
    report_start = datetime.combine(report.as_of, time(0, 0), tzinfo=UTC)

    edges = conn.execute(
        text(
            """
            SELECT e.id, e.dst_id, c.name, e.weight, e.confidence
            FROM edge e JOIN entity c ON c.id = e.dst_id
            WHERE e.src_id = :f AND e.type = 'CONTAINS'
              AND e.valid_from = :rdt AND e.known_at = :k
            """
        ),
        {"f": fund_id, "rdt": report_start, "k": report.known_at},
    ).all()
    covered = sum((e.weight for e in edges), ZERO)
    for e in edges:
        out.names[e.dst_id] = e.name
        out.paths.append(
            ExposurePath(fund_id, label, e.dst_id, value * e.weight, "fund", e.id, e.confidence)
        )
        _add(out.by_company, e.dst_id, value * e.weight)
    synthetic = conn.execute(
        text(
            """
            SELECT e.id, e.dst_id, c.name, e.weight, e.confidence
            FROM edge e JOIN entity c ON c.id = e.dst_id
            WHERE e.src_id = :f AND e.type = 'SYNTHETIC'
              AND e.valid_from = :rdt AND e.known_at = :k
            """
        ),
        {"f": fund_id, "rdt": report_start, "k": report.known_at},
    ).all()
    for e in synthetic:
        out.names[e.dst_id] = e.name
        out.paths.append(
            ExposurePath(fund_id, label, e.dst_id, value * e.weight, "swap", e.id, e.confidence)
        )
        _add(out.synthetic_by_company, e.dst_id, value * e.weight)
    rest = value * (ONE - covered)
    reason = (
        "cash, collateral, derivatives and unmatched names; see the breakdown"
        if rest >= 0
        else "the filing's weights add to more than 100% of net assets (leverage or negative cash)"
    )
    out.not_looked_through.append(NotLookedThrough(name, rest, reason, fund_id, label))
    _breakdown(conn, out, fund_id, name, label, value, rest, report)

    # Country comes from the filing's own per-line country, so it needs no name matching.
    lines = conn.execute(
        text(
            """
            SELECT coalesce(country, 'Unknown') AS country, sum(pct_val) AS pct
            FROM fund_holding
            WHERE fund_id = :f AND as_of = :rd AND known_at = :k
              AND asset_cat = ANY(:cats) AND payoff_profile = 'Long'
            GROUP BY 1
            """
        ),
        {"f": fund_id, "rd": report.as_of, "k": report.known_at, "cats": list(COVERED_CATS)},
    ).all()
    placed = ZERO
    for ln in lines:
        part = value * ln.pct / 100
        placed += part
        _add(out.by_country, ln.country, part)
    _add(out.by_country, "Not equity / not reported", value - placed)
