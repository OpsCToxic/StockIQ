# 0006 — Share classes: price rows carry the ticker; holdings stay one row per entity

- **Status:** Accepted
- **Date:** 2026-11-08

## Context
`entity` is one row per company (one per CIK; one per SEC series for funds). A company with two
listed classes (GOOG/GOOGL, BRK-A/BRK-B) has two tickers and two different prices on one entity.
`price_bar` was keyed on `(security_id, ts)`, so the second class would collide with the first.
Found while building the Massive prices connector, before any price data was stored.

## Options
| Option | Pros | Cons |
|---|---|---|
| Add a `security` table (one row per tradable ticker) and repoint holding, lot, price_bar | Cleanest model | Remaps already-imported holdings; ambiguous for funds with several classes (VOO vs VFIAX share one entity); big change for a personal tool |
| Carry `ticker` on price and corporate-action rows; keep holdings per entity | Small, no data loss, nothing ambiguous | Holding still one row per entity |
| Store only one "primary" ticker per entity | Simple | Arbitrary choice; loses data |

## Decision
Carry the ticker. `price_bar` is keyed on `(security_id, ticker, ts)` and `corporate_action` has a
`ticker`. `holding` keeps one row per entity and records the ticker held and the broker-reported
`market_value` at `as_of`. Exposure uses the broker's value at the snapshot, so it needs no price
lookup; prices are for revaluation between snapshots and for attribution (Phase 3).

## Consequences
- The CSV import aborts if two symbols map to one company in the same file, rather than
  overwriting a row. If that comes up (holding GOOG and GOOGL together), revisit with a
  `security` table.
- Entity-level return series (attribution, event studies) must choose a ticker per entity; do it
  explicitly, not by accident.
- Tickers are matched through currently open aliases, and the SEC files carry no ticker history.
  Three consequences, found in the quant review of 2026-11-08:
  - **Missing history:** a ticker delisted or renamed before the first seed has no (or a changed)
    entity, so a still-listed company can lose its pre-rename history (survivorship bias).
  - **Contamination, the worse case:** if ticker X belonged to company A and now belongs to B,
    a backfill attaches A's older bars to B, which shows up as a fake price jump in B's series.
  - **Not reproducible:** the rows written depend on alias state at upsert time, and
    `ON CONFLICT DO NOTHING` never repairs them, so re-parsing from raw can differ from the first
    run (against invariant 4).
  Fix before any Phase 3 or 5 return series: give ticker aliases real historical validity (from
  Massive ticker events or OpenFIGI), then join price rows with a validity window. Until then, use
  the stored prices only for recent dates and for currently held securities.
