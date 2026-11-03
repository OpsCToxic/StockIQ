---
name: point-in-time
description: How to write StockIQ queries and analytics that avoid look-ahead bias — known-time vs event-time, as_of parameters, filing lags, and the tests/pit suite. Use for any code that reads time series, filings, holdings history, signals, or computes anything as of a past date.
---

# Point-in-time correctness

## Two clocks
- **Event time:** when it happened (trade date, period end, quarter end, `valid_from`).
- **Known time:** when it could have been known (`known_at`: filing acceptance, disclosure date,
  article publish time, ingestion time for our own derived data).

Every table that feeds analytics has both. Backtests, event studies, lead/lag tests, and historical
attribution filter on **known time ≤ as_of**.

## Typical lags to respect
| Data | Known at |
|---|---|
| Form 4 | filing acceptance (~2 business days after trade) |
| 13F | filing date (up to 45 days after quarter end) |
| N-PORT fund holdings | public filing date (~60 days after period) |
| Congressional trades | disclosure date (up to ~45 days) |
| Short interest | FINRA publication date, not settlement date |
| 10-K/10-Q relationships | filing acceptance time |
| Earnings dates | the version of the calendar known at as_of (dates move) |
| Factor loadings | `window_end < as_of` |

## Code rules
- Analytics functions take `as_of: datetime` explicitly. No `now()`/`today()` inside
  `stockiq.modules` (enforced by INV-PIT in `scripts/check_invariants.py`).
- Put the known-time filter in the query, not in pandas afterwards.
- Universe and constituents are resolved as of `as_of` (no survivorship).
- Market-model betas for abnormal returns are estimated on a window that ends before the event window.

```sql
-- good
SELECT * FROM insider_trade
WHERE entity_id = :eid AND known_at <= :as_of;
-- bad: trade_date is event time
SELECT * FROM insider_trade WHERE entity_id = :eid AND trade_date <= :as_of;
```

## Tests (tests/pit/)
For each analytics function, build a fixture where a fact's event time is before `as_of` but its
known time is after, and assert it is excluded. Phase 5 gate: all pit tests green.
