from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class PriceBar(BaseModel):
    ticker: str
    ts: datetime  # end of the daily window (the 4 PM ET close, in UTC)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal  # can be fractional
    vwap: Decimal | None = None


class Split(BaseModel):
    ticker: str
    ex_date: date
    split_from: Decimal  # old shares
    split_to: Decimal  # new shares
    source_id: str


class Dividend(BaseModel):
    ticker: str
    ex_date: date
    cash_amount: Decimal
    currency: str | None = None
    declared_at: date | None = None
    pay_date: date | None = None
    source_id: str


MassiveRecord = PriceBar | Split | Dividend
