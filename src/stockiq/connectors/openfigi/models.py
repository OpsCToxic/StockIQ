from pydantic import BaseModel


class FigiMatch(BaseModel):
    ticker: str  # as we hold it (e.g. BRK-B), not OpenFIGI's spelling
    composite_figi: str
    share_class_figi: str | None = None
    name: str | None = None
    security_type: str | None = None


class FigiMiss(BaseModel):
    ticker: str
    reason: str  # "not_found" or "ambiguous"


FigiRecord = FigiMatch | FigiMiss
