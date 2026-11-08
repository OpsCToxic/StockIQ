from pydantic import BaseModel


class SicRecord(BaseModel):
    cik: str  # 10-digit, zero-padded
    sic: str  # 4-digit SIC code
    description: str
    span: str  # the JSON snippet exactly as served, kept as edge evidence
