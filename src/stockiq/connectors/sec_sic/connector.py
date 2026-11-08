"""Sector classification from SEC submissions (SIC code and description), as IN_SECTOR edges.

Each company's `https://data.sec.gov/submissions/CIK##########.json` is stored raw (gzipped), then
the SIC fields become an IN_SECTOR edge company -> sector, with the verbatim JSON snippet as
evidence. A sector is an entity of type `sector` named like "SIC 3571 Electronic Computers".
SEC gives only the current SIC, so edges are known from the fetch time (never backdated), and a
changed SIC closes the old edge and opens a new one.
"""

import gzip
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import Connection, text

from stockiq.connectors.base import BaseConnector, Cursor, RawPayload, StoredPayload
from stockiq.connectors.sec_sic.models import SicRecord
from stockiq.connectors.sec_tickers.client import sec_client
from stockiq.core.config import Settings

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
KIND = "sec_submissions"
SPAN = re.compile(r'"sic"\s*:\s*"[^"]*"\s*,\s*"sicDescription"\s*:\s*"[^"]*"')


def _body(raw: RawPayload) -> bytes:
    return gzip.decompress(raw.body) if raw.body[:2] == b"\x1f\x8b" else raw.body


class SecSicConnector(BaseConnector[SicRecord]):
    name = "sec_sic"
    schedule = "batch"

    def __init__(self, client: Any, ciks: list[str], now: datetime | None = None) -> None:
        self._client = client
        self._ciks = sorted({c.zfill(10) for c in ciks})
        self._now = now
        self.skipped: list[str] = []

    @classmethod
    def from_settings(cls, settings: Settings, ciks: list[str]) -> "SecSicConnector":
        return cls(sec_client(settings.sec_user_agent), ciks)

    async def fetch(self, since: Cursor) -> tuple[list[RawPayload], Cursor]:
        now = self._now or datetime.now(UTC)
        payloads = []
        for cik in self._ciks:
            url = SUBMISSIONS_URL.format(cik=cik)
            try:
                response = await self._client.get(url)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    self.skipped.append(f"{cik} (404)")
                    continue
                raise
            digest = hashlib.sha256(response.content).hexdigest()[:12]
            payloads.append(
                RawPayload(
                    source_id=f"submissions-{cik}-{now:%Y-%m-%d}-{digest}",
                    ext="json.gz",
                    body=gzip.compress(response.content),
                    fetched_at=now,
                    url=url,
                    published_at=now,
                    kind=KIND,
                )
            )
        return payloads, {"last_run": now.isoformat()}

    def parse(self, raw: RawPayload) -> list[SicRecord]:
        body = _body(raw)
        data = json.loads(body)
        sic, description = str(data.get("sic") or ""), str(data.get("sicDescription") or "")
        span = SPAN.search(body.decode("utf-8"))
        if not sic.isdigit() or not description or span is None:
            self.skipped.append(str(data.get("cik") or raw.source_id))
            return []
        return [
            SicRecord(
                cik=str(data["cik"]).zfill(10), sic=sic, description=description, span=span.group(0)
            )
        ]

    def upsert(self, conn: Connection, stored: StoredPayload, records: list[SicRecord]) -> None:
        at = stored.raw.fetched_at
        for rec in records:
            company = conn.execute(
                text("SELECT id FROM entity WHERE cik = :c AND type = 'company'"), {"c": rec.cik}
            ).scalar_one_or_none()
            if company is None:
                self.skipped.append(f"{rec.cik} (no entity)")
                continue
            sector_name = f"SIC {rec.sic} {rec.description}"
            sector = conn.execute(
                text("SELECT id FROM entity WHERE type = 'sector' AND name = :n"),
                {"n": sector_name},
            ).scalar_one_or_none()
            if sector is None:
                sector = conn.execute(
                    text(
                        "INSERT INTO entity (name, type, public, known_at) "
                        "VALUES (:n, 'sector', false, :at) RETURNING id"
                    ),
                    {"n": sector_name, "at": at},
                ).scalar_one()
            current = conn.execute(
                text(
                    "SELECT id, dst_id FROM edge WHERE src_id = :c AND type = 'IN_SECTOR' "
                    "AND valid_to IS NULL"
                ),
                {"c": company},
            ).all()
            if any(e.dst_id == sector for e in current):
                continue  # unchanged
            conn.execute(
                text(
                    "UPDATE edge SET valid_to = :at WHERE src_id = :c AND type = 'IN_SECTOR' "
                    "AND valid_to IS NULL AND valid_from < :at"
                ),
                {"c": company, "at": at},
            )
            edge_id = conn.execute(
                text(
                    """
                    INSERT INTO edge
                        (src_id, dst_id, type, weight, valid_from, confidence, known_at)
                    VALUES (:c, :s, 'IN_SECTOR', 1, :at, 1.0, :at)
                    ON CONFLICT (src_id, dst_id, type, valid_from, known_at) DO NOTHING
                    RETURNING id
                    """
                ),
                {"c": company, "s": sector, "at": at},
            ).scalar_one_or_none()
            if edge_id is None:
                continue
            conn.execute(
                text(
                    "INSERT INTO edge_evidence (edge_id, doc_id, section, span_text, url) "
                    "VALUES (:e, :d, 'sic', :span, :url) ON CONFLICT DO NOTHING"
                ),
                {"e": edge_id, "d": stored.doc_id, "span": rec.span, "url": stored.raw.url or ""},
            )
            conn.execute(
                text("UPDATE entity SET sector_id = :s WHERE id = :c"), {"s": sector, "c": company}
            )
