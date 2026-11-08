"""Plain-text rendering of a look-through exposure. A library module: the commands import it."""

from decimal import Decimal

from stockiq.graph.exposure import Exposure


def _money(v: Decimal) -> str:
    return f"{v:>12,.2f}"


def render(x: Exposure, top: int = 15) -> str:
    if not x.snapshot_as_of:
        return f"No holdings snapshot known as of {x.as_of:%Y-%m-%d %H:%M}."
    total = x.total_value
    lines = [
        f"Look-through exposure as of {x.as_of:%Y-%m-%d %H:%M %Z}",
        f"Total value: {_money(total).strip()}",
    ]
    for acct, snap in sorted(x.snapshot_as_of.items()):
        lines.append(f"Account {acct} snapshot: {snap:%Y-%m-%d %H:%M}")
    for fund, d in sorted(x.fund_report_dates.items()):
        lines.append(f"Fund data for {fund}: as of {d}  (quarterly, about a 60-day lag)")
    lines += ["", f"By company (top {top}):"]
    ranked = sorted(x.by_company.items(), key=lambda kv: kv[1], reverse=True)
    for entity_id, v in ranked[:top]:
        lines.append(f"  {x.names[entity_id][:34]:<34} {_money(v)}  {v / total:>7.2%}")
    rest = sum((v for _, v in ranked[top:]), Decimal(0))
    more = f"{len(ranked) - top} more companies" if len(ranked) > top else ""
    lines.append(f"  {more:<34} {_money(rest)}  {rest / total:>7.2%}")
    if x.synthetic_by_company:
        lines += ["", "Economic exposure, including swaps (can exceed your money):"]
        econ = sorted(x.economic_by_company.items(), key=lambda kv: kv[1], reverse=True)
        for entity_id, v in econ[:5]:
            lines.append(f"  {x.names[entity_id][:34]:<34} {_money(v)}  {v / total:>7.2%}")
        lines.append(
            "  Swap exposure is the filed notional over fund net assets, as of the fund's "
            "report date; leveraged funds rebalance daily."
        )
    for title, bucket in (
        ("By SIC division (funded value; swaps not included)", x.by_division),
        ("By SIC industry (funded value, top 8)", x.by_sector),
    ):
        lines += ["", f"{title}:"]
        for name, v in sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)[:8]:
            lines.append(f"  {name[:50]:<50} {_money(v)}  {v / total:>7.2%}")
    lines += ["", "By country:"]
    for name, v in sorted(x.by_country.items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"  {name[:34]:<34} {_money(v)}  {v / total:>7.2%}")
    lines += ["", "What the rest of each fund holds, by the filing's own categories:"]
    for p in x.breakdown:
        lines.append(
            f"  {p.holding:<6} {p.label[:44]:<44} {_money(p.value)}  {p.value / total:>7.2%}"
            f"  ({p.fund_share:.0%} of the fund, {p.lines} lines)"
        )
    lines.append(
        "  Derivatives are at fair value so they can be negative; money-market holdings can"
        " exceed 100% of a fund that holds swaps."
    )
    lines.append(f"  {'Cash':<34} {_money(x.cash)}  {x.cash / total:>7.2%}")
    lines += [
        "",
        f"Companies {_money(x.company_total).strip()} + cash, collateral and other "
        f"{_money(x.unlooked_total).strip()} + cash {_money(x.cash).strip()} "
        f"= {_money(x.reconciles_to).strip()} vs broker total {_money(total).strip()}",
        f"Covered by company-level look-through: {x.covered_fraction:.1%}",
    ]
    return "\n".join(lines)
