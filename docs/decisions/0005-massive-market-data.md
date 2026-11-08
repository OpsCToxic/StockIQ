# 0005 — Massive (formerly Polygon.io) as market-data provider

- **Status:** Accepted
- **Date:** 2026-11-02

## Context
Exposure look-through, attribution, event studies and signal lead/lag tests all need daily prices,
including for every constituent inside Cameron's ETFs, which is well over 500 symbols. See "Data
sources and ingestion" and "Analytics modules" in docs/architecture.md. Use is personal and
non-commercial, and Cameron wants to spend as little as possible for the proof of concept.

Findings (2026-11-02, from the providers' own pages unless noted):
- **Massive** `GET /v2/aggs/grouped/locale/us/market/stocks/{date}` returns open, high, low, close,
  volume and VWAP for all US stocks on a date in one call. It is split-adjusted by default and is
  included in every Stocks plan. History: Basic (free) 2 years, Starter 5, Developer 10,
  Advanced all. Free is 5 calls per minute. The docs do not mention dividend adjustment.
  Paid individual plans are reported at about $29 (Starter), $79 (Developer), $199 (Advanced); the
  exact current prices were not confirmed.
- **Tiingo** free is 50 requests per hour, 1,000 per day, 500 unique symbols per month, over 30 years
  of history. Power is $30 per month (about 110,000 symbols). Personal "internal use only" license.
- **Yahoo Finance** has no official API. yfinance uses undocumented endpoints, has long history and
  dividends, but breaks often, throttles unpredictably, and Yahoo's terms restrict automated access.
  (Not checked this session; from general knowledge.)

## Options
| Option | Pros | Cons | Cost |
|---|---|---|---|
| Massive free | All tickers in one call per date; documented API and limits; covers ETF look-through | Only 2 years of history; 5 calls per minute; dividend adjustment unconfirmed; personal-use license of free plan unconfirmed | Free |
| Massive Starter / Developer | 5 or 10 years of history; unlimited calls | Monthly fee | About $29 / $79 per month |
| Tiingo free | 30+ years of history; adjusted | 500 symbols per month cannot cover ETF constituents | Free |
| Tiingo Power | Decades of history; 110k symbols | Monthly fee; terms for keeping data after cancelling unchecked | $30 per month |
| Yahoo Finance (yfinance) | Free; long history; dividends | Unofficial and unstable; terms restrict automated access (invariant 7); silent changes risk corrupting returns | Free |

## Decision
Use Massive on the free plan for the proof of concept. Upgrade (Starter for 5 years, Developer for
10) when 2 years of history becomes the limit, expected at Phase 5 event studies. Yahoo Finance is
not adopted. Tiingo remains the fallback if Massive's terms or limits change.

## Consequences
- Add a Massive prices connector in Phase 1 (`connectors/massive/`), following the standard
  contract: raw first, idempotent upsert keyed on ticker and date, shared rate limiter set to
  5 calls per minute. Fetch one grouped-daily call per trading day; a 2-year backfill is about
  500 calls (roughly 100 minutes), then one call a day.
- Store **unadjusted** prices plus corporate actions (splits, dividends) and compute adjusted
  series ourselves. Massive adjusts to the date you fetch, which would break point-in-time
  queries (invariant 2). Request `adjusted=false` and fetch splits and dividends separately.
- Dividends and total return: Cameron confirmed on 2026-11-07 that the free plan includes
  dividends, so total return does not need a separate dividend source. Verify against the
  endpoint when the connector is built.
- License (read 2026-11-07, Individuals Terms and Market Data Terms, both updated 2026-11-03): the
  Individuals Terms cover free and paid individual plans for "your own personal, non-commercial,
  and non-business purposes", and the Market Data Terms allow storing the data and using it for
  "your own research, analysis and investment activities". A self-hosted Postgres of daily prices
  for personal analytics fits. Limits to respect:
  - Never share or display the raw prices to anyone else (no hosted dashboard, export or API for others).
  - Never use the prices to train, fine-tune or distill an ML model.
  - No business or commercial use, and no index or benchmark built from the data.
  - On downgrade or cancellation, delete stored data within 30 days (backups within 90). Derived
    results that contain no raw Information may be kept.
  - Not verified: Nasdaq-listed data falls under the UTP subscriber agreement (summary only), the
    Businesses Terms were only partly read, and the pricing page was not checked. Terms can change.
    Not legal advice.
- Event studies with fewer than 8 past occurrences are already greyed out (invariant 5). With
  2 years of history, only quarterly events (earnings) reach n of about 8; rarer events will show
  as greyed out until the history is longer.
- Secrets: the API key lives in `.env`, never in code or logs.

**Revisit if:** 2 years of history blocks a gate, Massive changes its free tier or terms, the
rate limit makes daily refresh impractical, or intraday data is needed (then compare Massive's
paid tiers with alternatives).
