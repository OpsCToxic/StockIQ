"""What each holding is made of, and what your money really rides on.

Two views, both built from the look-through result with nothing hidden:

* `build_holdings`: one row per holding, split into segments that add up to the holding's value
  exactly. Company stock, money-market funds and other collateral, equity we could not match, and
  what a fund owes on its swaps (a negative segment, drawn stepping back from the total).
* `build_exposure_bars`: your exposure to each company, funded stock plus swap exposure, as a
  share of your portfolio. It can pass 100% because swaps are leverage, not money you hold.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from stockiq.graph.exposure import BreakdownItem, BreakdownPart, Exposure, ExposurePath

PROVISIONAL_BELOW = Decimal("0.9")
ZERO = Decimal(0)

SegmentKind = Literal["stock", "cash", "swap_owed", "unmatched", "other"]


class SegmentOut(BaseModel):
    kind: SegmentKind
    label: str
    value: Decimal  # dollars of your holding; negative for what a fund owes
    share: Decimal  # of this holding's value; negative segments step back from the total
    edge_id: int | None = None  # fetch /edges/{edge_id}/evidence for the filing text behind it
    provisional: bool = False  # a company match under 0.9 confidence, awaiting review
    note: str | None = None  # how to read it, shown on hover


class HoldingOut(BaseModel):
    holding_id: int
    holding: str  # ticker
    name: str
    value: Decimal
    share: Decimal  # of the portfolio
    report_as_of: date | None  # the fund filing these segments come from; None for a stock
    segments: list[SegmentOut]  # in the order they are drawn; their values add up to `value`


class ExposureBarOut(BaseModel):
    company_id: int
    name: str
    funded: Decimal  # dollars of stock you hold in it, directly and through funds
    swap: Decimal  # dollars of swap exposure to it (not money you hold)
    funded_share: Decimal
    swap_share: Decimal
    total_share: Decimal  # of your portfolio; can pass 1 when swaps are involved
    swap_edge_id: int | None = None


def money_short(value: Decimal) -> str:
    v = abs(value)
    for limit, suffix in (
        (Decimal(10) ** 9, "B"),
        (Decimal(10) ** 6, "M"),
        (Decimal(10) ** 3, "K"),
    ):
        if v >= limit:
            return f"${v / limit:,.2f}{suffix}"
    return f"${v:,.0f}"


def _provisional(path: ExposurePath) -> bool:
    return path.confidence is not None and path.confidence < PROVISIONAL_BELOW


def _item_segment(item: BreakdownItem, holding_value: Decimal) -> SegmentOut:
    share = item.your_value / holding_value if holding_value else ZERO
    if item.reference is not None:
        who = item.counterparty or "the counterparty"
        size = f" (notional {money_short(item.notional)})" if item.notional is not None else ""
        return SegmentOut(
            kind="swap_owed",
            label=f"{who}: swap on {item.reference}",
            value=item.your_value,
            share=share,
            edge_id=item.edge_id,
            note=(
                f"Swap with {who} on {item.reference}{size}, at fair value "
                f"{money_short(item.fund_value) if item.fund_value is not None else 'n/a'}. "
                "A negative fair value is something the fund owes, so it offsets collateral."
            ),
        )
    held = money_short(item.fund_value) if item.fund_value is not None else "n/a"
    return SegmentOut(
        kind="cash",
        label=item.title or item.name,
        value=item.your_value,
        share=share,
        note=f"Held by the fund: {held} as filed",
    )


def _stock_segments(
    paths: list[ExposurePath], names: dict[int, str], holding_value: Decimal, top: int
) -> list[SegmentOut]:
    """Company stock inside a holding: the largest `top` companies, then one 'Other' segment."""
    ranked = sorted(paths, key=lambda p: p.value, reverse=True)
    shown, rest = ranked[:top], ranked[top:]
    out = [
        SegmentOut(
            kind="stock",
            label=names[p.company_id],
            value=p.value,
            share=p.value / holding_value if holding_value else ZERO,
            edge_id=p.edge_id,
            provisional=_provisional(p),
            note="Provisional match, waiting for review" if _provisional(p) else None,
        )
        for p in shown
    ]
    if rest:
        total = sum((p.value for p in rest), ZERO)
        out.append(
            SegmentOut(
                kind="stock",
                label=f"Other companies ({len(rest)})",
                value=total,
                share=total / holding_value if holding_value else ZERO,
                note="The rest of the stock in this holding; every company is in the table below",
            )
        )
    return out


def _remainder_segments(parts: list[BreakdownPart], holding_value: Decimal) -> list[SegmentOut]:
    """The non-company part of a fund, line by line, ordered so positives come first and what
    the fund owes comes last (the chart steps back over it)."""
    unmatched: list[SegmentOut] = []
    positives: list[SegmentOut] = []
    negatives: list[SegmentOut] = []
    misc = ZERO  # futures and other derivatives with no reference, other net assets, no filing
    misc_notes: list[str] = []
    for part in parts:
        share = part.value / holding_value if holding_value else ZERO
        if part.bucket == "unmatched_equity":
            unmatched.append(
                SegmentOut(
                    kind="unmatched",
                    label="Equity not matched to a company",
                    value=part.value,
                    share=share,
                    note=f"{part.lines} filed stock lines not tied to a company (review queue)",
                )
            )
        elif part.bucket in ("cash", "debt"):
            positives += [_item_segment(i, holding_value) for i in part.items]
        elif part.bucket == "derivatives":
            has_futures = False
            for item in part.items:
                if item.reference is not None:
                    seg = _item_segment(item, holding_value)
                    (negatives if seg.value < 0 else positives).append(seg)
                else:
                    misc += item.your_value
                    has_futures = True
            if has_futures:
                misc_notes.append("futures and other derivatives")
        elif part.bucket == "unknown":
            positives.append(
                SegmentOut(
                    kind="other",
                    label="No fund holdings filing known yet",
                    value=part.value,
                    share=share,
                )
            )
        else:  # "other": net other assets and liabilities, and rounding
            misc += part.value
            misc_notes.append("net other assets and liabilities")
    out = unmatched + sorted(positives, key=lambda s: s.value, reverse=True)
    if misc:
        seg = SegmentOut(
            kind="other",
            label="Other, net",
            value=misc,
            share=misc / holding_value if holding_value else ZERO,
            note="Net of " + " and ".join(sorted(set(misc_notes))),
        )
        (positives if misc > 0 else negatives).append(seg)
        out = unmatched + sorted(positives, key=lambda s: s.value, reverse=True)
    return out + sorted(negatives, key=lambda s: s.value)


def build_holdings(x: Exposure, top: int = 6) -> list[HoldingOut]:
    stock: dict[int, list[ExposurePath]] = defaultdict(list)
    for p in x.paths:
        if p.kind in ("direct", "fund"):
            stock[p.holding_id].append(p)
    parts: dict[int, list[BreakdownPart]] = defaultdict(list)
    for part in x.breakdown:
        parts[part.holding_id].append(part)

    rows: list[HoldingOut] = []
    for holding_id in sorted(set(stock) | set(parts)):
        paths, fund_parts = stock.get(holding_id, []), parts.get(holding_id, [])
        value = sum((p.value for p in paths), ZERO) + sum((p.value for p in fund_parts), ZERO)
        label = paths[0].holding if paths else fund_parts[0].holding
        is_stock = bool(paths) and all(p.kind == "direct" for p in paths)
        name = (
            x.names[paths[0].company_id]
            if is_stock
            else (fund_parts[0].fund if fund_parts else label)
        )
        segments = _stock_segments(paths, x.names, value, 1 if is_stock else top)
        segments += _remainder_segments(fund_parts, value)
        rows.append(
            HoldingOut(
                holding_id=holding_id,
                holding=label,
                name=name,
                value=value,
                share=value / x.total_value if x.total_value else ZERO,
                report_as_of=None if is_stock else x.fund_report_dates.get(name),
                segments=segments,
            )
        )
    return sorted(rows, key=lambda r: r.value, reverse=True)


def build_exposure_bars(x: Exposure, limit: int = 8) -> list[ExposureBarOut]:
    if not x.total_value:
        return []
    swap_edge: dict[int, int] = {}
    for p in x.paths:
        if p.kind == "swap" and p.edge_id is not None:
            swap_edge.setdefault(p.company_id, p.edge_id)
    bars = []
    for company_id, total in x.economic_by_company.items():
        funded = x.by_company.get(company_id, ZERO)
        swap = x.synthetic_by_company.get(company_id, ZERO)
        bars.append(
            ExposureBarOut(
                company_id=company_id,
                name=x.names[company_id],
                funded=funded,
                swap=swap,
                funded_share=funded / x.total_value,
                swap_share=swap / x.total_value,
                total_share=total / x.total_value,
                swap_edge_id=swap_edge.get(company_id),
            )
        )
    return sorted(bars, key=lambda b: b.total_share, reverse=True)[:limit]
