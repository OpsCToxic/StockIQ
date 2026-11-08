from pydantic import BaseModel


class SecCompany(BaseModel):
    cik: str  # 10-digit, zero-padded
    name: str
    ticker: str
    exchange: str | None = None


class SecFund(BaseModel):
    filer_cik: str  # trust CIK; shared by many series
    series_id: str
    class_id: str
    ticker: str


SecRecord = SecCompany | SecFund
