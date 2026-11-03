---
name: new-connector
description: Contract, layout, and checklist for adding a StockIQ data-source connector (SEC, FINRA, market data, news, Reddit, StockTwits, HN, brokerage). Use whenever creating or substantially changing anything under src/stockiq/connectors/.
---

# New connector

Every source is isolated in its own package so one API changing or going dark never takes down
another module.

## Layout
```
src/stockiq/connectors/<source>/
  __init__.py
  client.py      # HTTP/API calls only; uses base.RateLimitedClient
  connector.py   # class <Source>Connector(BaseConnector)
  models.py      # Pydantic models for parsed records
  README.md      # endpoint(s), auth, rate limits, terms notes, cadence, known quirks
tests/unit/connectors/test_<source>.py
tests/fixtures/<source>/*.json|xml|txt   # real raw payloads (trimmed), never secrets
```

## Contract (implemented by BaseConnector in connectors/base.py)
```python
class BaseConnector(ABC):
    name: str                      # e.g. "sec_form4"
    schedule: Literal["batch", "poller"]
    async def fetch(self, since: Cursor) -> list[RawPayload]: ...
    def parse(self, raw: RawPayload) -> list[Record]: ...
```
The base class runs: `fetch` → write each raw payload to object storage at
`raw/<source>/<yyyy>/<mm>/<dd>/<source_id>.<ext>` (with content hash) → `parse` → idempotent upsert
keyed on the source's own ID → advance cursor → publish `source.<name>.ingested` on Redis Streams.

## Rules
- **Raw first.** Never parse before the raw payload is persisted. Re-parse from raw; don't re-fetch.
- **Point-in-time.** Every record carries `known_at` (when we/the public could have known it:
  filing acceptance time, disclosure date, article publish time) separately from the event time.
- **Rate limits** via the per-source token bucket in `base.py`. SEC: descriptive User-Agent with
  contact email from settings, ≤ 10 req/s, use daily index files instead of crawling.
- **Retries** with exponential backoff + jitter on 429/5xx; respect `Retry-After`.
- **Secrets** from `stockiq.core.config.Settings`; add any new variable to `.env.example`.
- **Terms.** Reddit is non-commercial free tier (100 QPM). News: store URL, headline, summary — not
  the full article. Market data: no redistribution. No prohibited HTML scraping.
- **Entity mapping** is not the connector's job beyond attaching identifiers the source gives
  (CIK, CUSIP, ticker, cashtag). The resolver maps them to `entity_id`.

## Checklist
1. Read the source's current official docs and terms; note limits in the README.
2. Save 2–3 real raw payloads to `tests/fixtures/<source>/` (strip anything personal).
3. Write `models.py`, `client.py`, `connector.py`.
4. Tests: parse each fixture; idempotency (parsing twice upserts once); cursor advance; `known_at`
   populated.
5. Register: Dagster asset/schedule in `orchestration/` for batch, or a worker entry for pollers.
6. `make lint test`.
