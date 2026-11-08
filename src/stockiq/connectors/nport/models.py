from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class NportHolding(BaseModel):
    seq: int  # position in the filing; stable, so a re-parse upserts the same rows
    name: str
    title: str | None = None
    cusip: str | None = None
    isin: str | None = None
    lei: str | None = None
    asset_cat: str | None = None  # EC = common equity, EP = preferred, DBT = debt, ...
    payoff_profile: str | None = None  # Long / Short / N/A
    country: str | None = None
    balance: Decimal | None = None
    val_usd: Decimal | None = None
    pct_val: Decimal | None = None  # percent of net assets (0.0684 means 0.0684%)
    swap_ref: str | None = None  # reference instrument of a swap (usually a ticker)
    notional: Decimal | None = None
    counterparty: str | None = None  # the other side of a swap
    swap_direction: str | None = None  # "long" if the fund receives the return
    span_text: str  # the holding's XML exactly as filed, kept as edge evidence


class NportReport(BaseModel):
    series_id: str
    series_name: str
    filer_cik: str
    report_date: date  # the holdings are as of this date
    known_at: datetime  # when the filing became public
    accession: str
    net_assets: Decimal | None = None
    total_assets: Decimal | None = None
    holdings: list[NportHolding]
