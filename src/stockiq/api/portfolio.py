"""Exposure X-ray API: response models and the routes.

`GET /portfolio/exposure?as_of=&top=` returns the look-through exposure: what each holding is
made of, what your money really rides on, the concentration flags and the caveats.
`GET /edges/{id}/evidence` returns the filing text behind a segment or a swap.
Read-only. The clock is read here, at the edge; everything below takes an explicit `as_of`.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Connection, text

from stockiq.api.composition import (
    ExposureBarOut,
    HoldingOut,
    build_exposure_bars,
    build_holdings,
)
from stockiq.core.db import get_engine
from stockiq.graph.exposure import Exposure, look_through
from stockiq.modules.exposure.concentration import Concentration, concentration

router = APIRouter()
PROVISIONAL_BELOW = Decimal("0.9")


class Line(BaseModel):
    name: str
    value: Decimal
    share: Decimal  # of the portfolio's value; economic shares can exceed 1


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


class BreakdownItemOut(BaseModel):
    """One filed line inside a breakdown category: a money-market fund, a swap, a debt holding."""

    name: str
    title: str | None
    your_value: Decimal  # dollars of your holding
    fund_value: Decimal | None  # the line's own value in the fund, as filed (USD)
    fund_share: Decimal | None  # of the fund's net assets
    notional: Decimal | None  # swaps only
    counterparty: str | None  # swaps only: who is on the other side
    direction: str | None  # swaps only: "long" if the fund receives the reference's return
    reference: str | None  # swaps only: what it follows
    edge_id: int | None  # fetch /edges/{edge_id}/evidence for the filing text behind a swap


class BreakdownOut(BaseModel):
    """One slice of a fund's non-company remainder, by the filing's own asset category."""

    holding: str
    fund: str
    bucket: str
    label: str
    value: Decimal  # dollars of your holding; derivatives can be negative
    share: Decimal  # of your portfolio
    fund_share: Decimal  # of the fund's net assets
    lines: int
    items: list[BreakdownItemOut]


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
    breakdown: list[BreakdownOut]
    fund_report_dates: dict[str, date]
    holdings: list[HoldingOut]  # what each holding is made of; segments add up to its value
    exposure: list[ExposureBarOut]  # your exposure by company, funded plus swaps
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
    if x.breakdown:
        caveats.append(
            "The remainder of each fund (cash, collateral, derivatives) is not company exposure. "
            "Derivatives are at fair value, so they can be negative, and money-market holdings can "
            "exceed 100% of a fund that holds swaps."
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
        breakdown=[
            BreakdownOut(
                holding=p.holding,
                fund=p.fund,
                bucket=p.bucket,
                label=p.label,
                value=p.value,
                share=p.value / total if total else Decimal(0),
                fund_share=p.fund_share,
                lines=p.lines,
                items=[
                    BreakdownItemOut(
                        name=i.name,
                        title=i.title,
                        your_value=i.your_value,
                        fund_value=i.fund_value,
                        fund_share=i.fund_share,
                        notional=i.notional,
                        counterparty=i.counterparty,
                        direction=i.direction,
                        reference=i.reference,
                        edge_id=i.edge_id,
                    )
                    for i in p.items
                ],
            )
            for p in x.breakdown
        ],
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
        holdings=build_holdings(x, top),
        exposure=build_exposure_bars(x),
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
    top: Annotated[int, Query(ge=1, le=1000)] = 15,
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
