from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class CsvPosition(BaseModel):
    symbol: str
    qty: Decimal
    price_paid: Decimal
    value: Decimal
    total_gain: Decimal

    @property
    def cost_basis(self) -> Decimal:
        # Total cost to the cent. Price Paid is rounded to 4 places, so qty * price_paid drifts.
        return self.value - self.total_gain


class CsvExport(BaseModel):
    generated_at: datetime  # when E*TRADE produced the file; the as_of of every row
    account_name: str
    positions: list[CsvPosition]
    cash: Decimal
    total_value: Decimal


CsvRecord = CsvExport
