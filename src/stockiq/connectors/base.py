"""Shared connector library: rate limiting, retries, cursor storage, raw-first run loop.

Contract (docs/architecture.md): `fetch(since) -> raw[]`, `parse(raw) -> records[]`. The run loop
persists each raw payload to object storage *before* parsing, then upserts idempotently, then
advances the cursor.
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from sqlalchemy import Connection, text
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from stockiq.core.storage import RawStore

Cursor = dict[str, Any]


@dataclass(frozen=True)
class RawPayload:
    source_id: str  # the source's own ID; the idempotency key
    ext: str
    body: bytes
    fetched_at: datetime
    url: str | None = None
    published_at: datetime | None = None  # when the source made it public (known time)
    kind: str = "raw"


@dataclass(frozen=True)
class StoredPayload:
    raw: RawPayload
    uri: str
    hash: str
    doc_id: int


class TokenBucket:
    """Per-source rate limit. `rate` tokens per second, burst of `capacity`."""

    def __init__(self, rate: float, capacity: int | None = None) -> None:
        self._rate = rate
        self._capacity = capacity if capacity is not None else max(1, int(rate))
        self._tokens = float(self._capacity)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self._rate)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class RateLimitedClient:
    """httpx wrapper: token bucket, retry with backoff and jitter on 429/5xx."""

    def __init__(
        self,
        rate_per_second: float,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        attempts: int = 5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._bucket = TokenBucket(rate_per_second)
        self._attempts = attempts
        self._client = httpx.AsyncClient(headers=headers, timeout=timeout, transport=transport)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._attempts),
            wait=wait_exponential_jitter(initial=1, max=60),
            retry=retry_if_exception(_retryable),
            reraise=True,
        ):
            with attempt:
                await self._bucket.acquire()
                response = await self._client.request(method, url, **kwargs)
                retry_after = response.headers.get("Retry-After")
                if response.status_code == 429 and retry_after and retry_after.isdigit():
                    await asyncio.sleep(min(int(retry_after), 120))
                response.raise_for_status()
                return response
        raise AssertionError("unreachable")

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()


def load_cursor(conn: Connection, source: str) -> Cursor:
    row = conn.execute(
        text("SELECT cursor FROM connector_cursor WHERE source = :s"), {"s": source}
    ).first()
    return dict(row[0]) if row else {}


def save_cursor(conn: Connection, source: str, cursor: Cursor) -> None:
    conn.execute(
        text(
            """
            INSERT INTO connector_cursor (source, cursor, updated_at)
            VALUES (:s, CAST(:c AS jsonb), now())
            ON CONFLICT (source) DO UPDATE SET cursor = EXCLUDED.cursor, updated_at = now()
            """
        ),
        {"s": source, "c": json.dumps(cursor)},
    )


def record_document(
    conn: Connection, source: str, raw: RawPayload, uri: str, content_hash: str
) -> int:
    """Idempotent on (source, source_id). A re-fetch of the same ID keeps the first raw_uri."""
    row = conn.execute(
        text(
            """
            INSERT INTO document (source, source_id, kind, url, published_at, raw_uri, hash)
            VALUES (:source, :sid, :kind, :url, :pub, :uri, :hash)
            ON CONFLICT (source, source_id) DO UPDATE SET source_id = EXCLUDED.source_id
            RETURNING id
            """
        ),
        {
            "source": source,
            "sid": raw.source_id,
            "kind": raw.kind,
            "url": raw.url,
            "pub": raw.published_at,
            "uri": uri,
            "hash": content_hash,
        },
    ).one()
    return int(row[0])


@dataclass
class RunResult:
    fetched: int = 0
    records: int = 0
    cursor: Cursor = field(default_factory=dict)


class BaseConnector[Record](ABC):
    name: str
    schedule: Literal["batch", "poller"] = "batch"

    @abstractmethod
    async def fetch(self, since: Cursor) -> tuple[list[RawPayload], Cursor]:
        """Return new raw payloads and the cursor to store once they are processed."""

    @abstractmethod
    def parse(self, raw: RawPayload) -> list[Record]: ...

    @abstractmethod
    def upsert(self, conn: Connection, stored: StoredPayload, records: list[Record]) -> None:
        """Idempotent upsert keyed on the source's own ID."""

    async def run(
        self,
        conn: Connection,
        store: RawStore,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        since = load_cursor(conn, self.name)
        payloads, next_cursor = await self.fetch(since)
        result = RunResult(fetched=len(payloads), cursor=next_cursor)
        for raw in payloads:
            # Raw first: persist before parsing.
            stored_raw = store.put(self.name, raw.source_id, raw.ext, raw.body, raw.fetched_at)
            doc_id = record_document(conn, self.name, raw, stored_raw.uri, stored_raw.hash)
            stored = StoredPayload(raw, stored_raw.uri, stored_raw.hash, doc_id)
            records = self.parse(raw)
            self.upsert(conn, stored, records)
            result.records += len(records)
        save_cursor(conn, self.name, next_cursor)
        if publish is not None:
            publish(
                f"source.{self.name}.ingested",
                {"fetched": result.fetched, "at": datetime.now(UTC).isoformat()},
            )
        return result
