"""Exposure X-ray API: response models, Sankey construction, and the routes.

`GET /portfolio/exposure?as_of=&top=` returns the look-through exposure with a Sankey graph and
the concentration flags. `GET /edges/{id}/evidence` returns what backs a flow in the Sankey.
Read-only. The clock is read here, at the edge; everything below takes an explicit `as_of`.
"""

from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Connection, text

from stockiq.core.db import get_engine
from stockiq.graph.exposure import Exposure, look_through
from stockiq.modules.exposure.concentration import Concentration, concentration

router = APIRouter()
PROVISIONAL_BELOW = Decimal("0.9")


class Line(BaseModel):
    name: str
    value: Decimal
    share: Decimal  # of the portfolio's value; economic shares can exceed 1


class SankeyNode(BaseModel):
    id: str
    label: str
    kind: Literal["portfolio", "holding", "company", "other", "unlooked", "cash"]


class SankeyLink(BaseModel):
    source: str
    target: str
    value: Decimal
    kind: Literal["direct", "fund", "swap", "unlooked", "cash", "other"]
    edge_id: int | None = None  # fetch /edges/{edge_id}/evidence for the source behind this flow
    confidence: Decimal | None = None
    provisional: bool = False


class Sankey(BaseModel):
    nodes: list[SankeyNode]
    links: list[SankeyLink]  # funded value only: flows add up to the portfolio
    swap_links: list[SankeyLink]  # swap exposure on top of that; it is not money you hold


class FlagOut(BaseModel):
    kind: str
    basis: str
    name: str
    value: Decimal
    share: Decimal
    threshold: Decimal


class HerfindahlOut(BaseModel):
    basis: str
    hhi: Decimal
    effective_n: Decimal
    companies: int
    covered_fraction: Decimal


class NotLookedThroughOut(BaseModel):
    holding: str
    label: str
    value: Decimal
    share: Decimal
    reason: str


class ExposureResponse(BaseModel):
    as_of: datetime
    snapshot_as_of: dict[str, datetime]
    total_value: Decimal
    cash: Decimal
    reconciles: bool  # companies + not looked through + cash equals the broker total
    covered_fraction: Decimal
    provisional_value: Decimal  # funded value that rests on a match below 0.9 confidence
    companies: list[Line]
    economic_companies: list[Line]
    industries: list[Line]
    divisions: list[Line]
    countries: list[Line]
    not_looked_through: list[NotLookedThroughOut]
    fund_report_dates: dict[str, date]
    sankey: Sankey
    flags: list[FlagOut]
    herfindahl: list[HerfindahlOut]
    caveats: list[str]


class EvidenceOut(BaseModel):
    doc_id: int
    section: str | None
    span_text: str | None
    url: str
    source: str
    published_at: datetime | None


class EvidenceResponse(BaseModel):
    edge_id: int
    edge_type: str
    from_entity: str
    to_entity: str
    weight: Decimal | None
    confidence: Decimal
    known_at: datetime
    total: int
    evidence: list[EvidenceOut]


def _lines(values: dict[str, Decimal], total: Decimal, limit: int | None = None) -> list[Line]:
    ranked = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
    if limit is not None:
        ranked = ranked[:limit]
    return [Line(name=n, value=v, share=v / total if total else Decimal(0)) for n, v in ranked]


def build_sankey(x: Exposure, top: int) -> Sankey:
    """Portfolio -> holdings -> companies. The `top` companies by funded value are shown; the rest
    are folded into one 'other companies' node so the graph stays readable."""
    funded = [p for p in x.paths if p.kind in ("direct", "fund")]
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for p in funded:
        totals[p.company_id] += p.value
    shown = {cid for cid, _ in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:top]}

    nodes: dict[str, SankeyNode] = {
        "portfolio": SankeyNode(id="portfolio", label="Your portfolio", kind="portfolio")
    }
    links: list[SankeyLink] = []
    to_holding: dict[str, Decimal] = defaultdict(Decimal)
    folded: dict[str, Decimal] = defaultdict(Decimal)

    def hold(hid: int, label: str) -> str:
        nid = f"h:{hid}"
        nodes.setdefault(nid, SankeyNode(id=nid, label=label, kind="holding"))
        return nid

    for p in funded:
        h = hold(p.holding_id, p.holding)
        to_holding[h] += p.value
        if p.company_id in shown:
            cid = f"c:{p.company_id}"
            nodes.setdefault(cid, SankeyNode(id=cid, label=x.names[p.company_id], kind="company"))
            links.append(
                SankeyLink(
                    source=h,
                    target=cid,
                    value=p.value,
                    kind="direct" if p.kind == "direct" else "fund",
                    edge_id=p.edge_id,
                    confidence=p.confidence,
                    provisional=p.confidence is not None and p.confidence < PROVISIONAL_BELOW,
                )
            )
        else:
            folded[h] += p.value
    if folded:
        nodes["other"] = SankeyNode(id="other", label="Other companies", kind="other")
        links += [
            SankeyLink(source=h, target="other", value=v, kind="other") for h, v in folded.items()
        ]
    for n in x.not_looked_through:
        h = hold(n.holding_id, n.holding or n.label)
        nodes.setdefault(
            "unlooked", SankeyNode(id="unlooked", label="Not looked through", kind="unlooked")
        )
        to_holding[h] += n.value
        links.append(SankeyLink(source=h, target="unlooked", value=n.value, kind="unlooked"))
    if x.cash:
        nodes["cash"] = SankeyNode(id="cash", label="Cash", kind="cash")
        links.append(SankeyLink(source="portfolio", target="cash", value=x.cash, kind="cash"))
    links += [
        SankeyLink(source="portfolio", target=h, value=v, kind="fund")
        for h, v in to_holding.items()
    ]

    swaps = [
        SankeyLink(
            source=f"h:{p.holding_id}",
            target=f"c:{p.company_id}",
            value=p.value,
            kind="swap",
            edge_id=p.edge_id,
            confidence=p.confidence,
            provisional=p.confidence is not None and p.confidence < PROVISIONAL_BELOW,
        )
        for p in x.paths
        if p.kind == "swap"
    ]
    for p in x.paths:
        if p.kind == "swap":
            nodes.setdefault(
                f"c:{p.company_id}",
                SankeyNode(id=f"c:{p.company_id}", label=x.names[p.company_id], kind="company"),
            )
    return Sankey(nodes=list(nodes.values()), links=links, swap_links=swaps)


def build_response(x: Exposure, c: Concentration, top: int) -> ExposureResponse:
    total = x.total_value
    named_funded = {x.names[i]: v for i, v in x.by_company.items()}
    named_econ = {x.names[i]: v for i, v in x.economic_by_company.items()}
    provisional = sum(
        (
            p.value
            for p in x.paths
            if p.kind == "fund" and p.confidence is not None and p.confidence < PROVISIONAL_BELOW
        ),
        Decimal(0),
    )
    caveats = [
        f"{fund}: fund holdings are as of {d} (public filings are quarterly, about a 60-day lag)"
        for fund, d in sorted(x.fund_report_dates.items())
    ]
    if x.synthetic_by_company:
        caveats.append(
            "Swap exposure is the filed notional over fund net assets at the fund's report date; "
            "leveraged funds rebalance daily, so treat it as approximate."
        )
    caveats.append(
        "Industries use SEC SIC codes: free but coarse (for example Manufacturing covers hardware, "
        "drugs and cars). Industry and division views count funded value only, not swaps."
    )
    if provisional:
        caveats.append(
            "Some fund holdings are matched to companies by fuzzy name at under 0.9 confidence; "
            "they are in the review queue."
        )
    return ExposureResponse(
        as_of=x.as_of,
        snapshot_as_of={str(k): v for k, v in x.snapshot_as_of.items()},
        total_value=total,
        cash=x.cash,
        reconciles=abs(x.reconciles_to - total) < Decimal("0.01"),
        covered_fraction=x.covered_fraction,
        provisional_value=provisional,
        companies=_lines(named_funded, total, 25),
        economic_companies=_lines(named_econ, total, 25),
        industries=_lines(x.by_sector, total, 25),
        divisions=_lines(x.by_division, total),
        countries=_lines(x.by_country, total),
        not_looked_through=[
            NotLookedThroughOut(
                holding=n.holding or n.label,
                label=n.label,
                value=n.value,
                share=n.value / total if total else Decimal(0),
                reason=n.reason,
            )
            for n in x.not_looked_through
        ],
        fund_report_dates=x.fund_report_dates,
        sankey=build_sankey(x, top),
        flags=[
            FlagOut(
                kind=f.kind,
                basis=f.basis,
                name=f.name,
                value=f.value,
                share=f.share,
                threshold=f.threshold,
            )
            for f in c.flags
        ],
        herfindahl=[
            HerfindahlOut(
                basis=h.basis,
                hhi=h.hhi,
                effective_n=h.effective_n,
                companies=h.companies,
                covered_fraction=h.covered_fraction,
            )
            for h in c.herfindahl
        ],
        caveats=caveats,
    )


def get_conn() -> Iterator[Connection]:
    """One read-only connection per request. Tests override this with their own transaction."""
    with get_engine().connect() as conn:
        yield conn


@router.get("/portfolio/exposure", response_model=ExposureResponse)
def portfolio_exposure(
    conn: Annotated[Connection, Depends(get_conn)],
    as_of: datetime | None = None,
    top: Annotated[int, Query(ge=1, le=100)] = 15,
) -> ExposureResponse:
    when = as_of or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    x = look_through(conn, when)
    if not x.snapshot_as_of:
        raise HTTPException(404, f"no holdings snapshot known as of {when:%Y-%m-%d %H:%M}")
    return build_response(x, concentration(x), top)


@router.get("/edges/{edge_id}/evidence", response_model=EvidenceResponse)
def edge_evidence(
    edge_id: int,
    conn: Annotated[Connection, Depends(get_conn)],
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> EvidenceResponse:
    edge = conn.execute(
        text(
            """
            SELECT e.id, e.type, s.name AS src, d.name AS dst,
                   e.weight, e.confidence, e.known_at
            FROM edge e JOIN entity s ON s.id = e.src_id JOIN entity d ON d.id = e.dst_id
            WHERE e.id = :i
            """
        ),
        {"i": edge_id},
    ).one_or_none()
    if edge is None:
        raise HTTPException(404, f"no edge {edge_id}")
    total = conn.execute(
        text("SELECT count(*) FROM edge_evidence WHERE edge_id = :i"), {"i": edge_id}
    ).scalar_one()
    rows = conn.execute(
        text(
            """
            SELECT v.doc_id, v.section, v.span_text, v.url, d.source, d.published_at
            FROM edge_evidence v JOIN document d ON d.id = v.doc_id
            WHERE v.edge_id = :i ORDER BY v.id LIMIT :n
            """
        ),
        {"i": edge_id, "n": limit},
    ).all()
    return EvidenceResponse(
        edge_id=edge.id,
        edge_type=edge.type,
        from_entity=edge.src,
        to_entity=edge.dst,
        weight=edge.weight,
        confidence=edge.confidence,
        known_at=edge.known_at,
        total=total,
        evidence=[
            EvidenceOut(
                doc_id=r.doc_id,
                section=r.section,
                span_text=r.span_text,
                url=r.url,
                source=r.source,
                published_at=r.published_at,
            )
            for r in rows
        ],
    )
