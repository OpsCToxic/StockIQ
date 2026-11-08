# massive

Daily prices, splits and dividends from Massive (formerly Polygon). ADR 0005 (provider), ADR 0006
(share-class keys). Personal, non-commercial use only: never show or share the raw prices, never
train a model on them, delete stored data within 30 days if the plan ends.

- **Prices:** `GET https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/{date}?adjusted=false`,
  one call per trading day for all tickers (about 12,500 rows). Stored **unadjusted**.
- **Corporate actions:** `GET /stocks/v1/dividends` and `/stocks/v1/splits`, filtered by ex date,
  paginated by `next_url`. Adjusted series are computed from these later, using only rows with
  `known_at <= as_of`.
- **Auth:** `MASSIVE_API_KEY` in `.env`, sent as a Bearer header (never in a URL or log).
- **Rate limit:** 5 calls/min on the free plan (ADR 0005); the client enforces it. Free history is
  2 years. A full backfill is about 500 calls, roughly 100 minutes.
- **Run:** `python -m stockiq.connectors.massive prices 2024-11-08` (loops in 20-day chunks, safe to
  stop and rerun) and `python -m stockiq.connectors.massive actions 2024-11-08`.
- **Verified live (2026-11-08):** weekends and holidays return HTTP 200 with zero results, which
  the connector skips; today's data is refused (403) before the close, so it only asks through
  yesterday in New York; the bar timestamp `t` is the 4 PM ET close in UTC; volume can be
  fractional; `next_url` has a cursor but no key.
- **Point-in-time:** a bar's `known_at` is its close. A dividend's is its declaration date (ex date
  if missing). The API gives no split announcement date, so a split's is its ex date (conservative).
  Corporate actions refetch a 30-day overlap each run; upserts are idempotent on Massive's own ID.
- **Which tickers:** only tickers with an open ticker alias get stored. Tickers delisted before the
  first entity seed have no entity, so their history is dropped (survivorship bias, ADR 0006).
- **Cross-check:** on 2026-11-06 the stored closes for TSLL, UUUU and VOO equal the last prices in
  the E*TRADE export.
- **Fixtures:** `tests/fixtures/massive/` are synthetic on purpose; real Massive responses must not
  be committed (redistribution).
- **Known doc gaps:** the docs don't state the per-minute limit on the free plan or what a holiday
  returns; the values above come from live calls.
