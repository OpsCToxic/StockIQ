# Roadmap

Build the graph first; every module depends on it. Each phase ends with something usable daily and a
**gate** that must pass before the next phase starts. `make gate PHASE=N` runs the automated part.

**Current phase: 2 (Exposure X-ray)**. Phase 1's manual gate (look-through total vs the broker
statement) is waiting for Cameron to confirm. Phase 0's CI check has not been run.

Status keys: `[ ]` todo · `[~]` in progress · `[x]` done · `[-]` dropped

---

## Phase 0 — Harness + skeleton
- [x] Claude Code harness (CLAUDE.md, agents, skills, commands, hooks)
- [x] Docker Compose (Postgres+Timescale+pgvector, Redis, MinIO), Makefile, CI
- [x] Alembic initialised, first empty migration (applied locally, revision 0001)
- [x] Reddit source → [ADR 0004](decisions/0004-arctic-shift-reddit-source.md): Arctic Shift API (accepted); not applying for the official Reddit Data API
- [x] Market-data provider → [ADR 0005](decisions/0005-massive-market-data.md): Massive free for the PoC; upgrade when history is the limit
- [x] Create a Massive account and API key (put it in `.env`); confirm the free plan's license and whether dividends are included. Done 2026-11-07: dividends included; personal-use license reviewed, see ADR 0005
- [~] Brokerage aggregator → ADR: **on hold** (Cameron, 2026-11-02). Proof of concept uses E*TRADE direct + CSV. Candidates if resumed: SnapTrade (lean), Plaid Investments
- [-] Request E*TRADE sandbox key; resolve open questions in [ADR 0002](decisions/0002-etrade-sign-on.md). Dropped by Cameron 2026-11-08: no E*TRADE API connector; holdings come from the CSV export
**Gate:** `make up && make lint test` green in CI.

## Phase 1 — Foundation: holdings + look-through
- [x] Core tables: entity, entity_alias, account, holding, lot, document, price_bar
- [x] Entity master seed: SEC company tickers + OpenFIGI. SEC ticker connector ran 2026-11-08 (8,009 companies, 12,303 funds, idempotent); OpenFIGI connector looks up FIGIs for given tickers on demand (migrations 0003, 0004)
- [x] Brokerage import: CSV first (aggregator on hold, see Phase 0). E*TRADE positions CSV import with reconciliation checks; parsed your real export successfully (migration 0005). Not loaded into the DB yet
- [-] E*TRADE sign-on connector with daily login (read endpoints only). Dropped by Cameron 2026-11-08; the read-only-scope question never needed an answer
- [x] N-PORT fund holdings connector (issuer daily files where available). SEC N-PORT filings via the series Atom feed, live run 2026-11-08: VOO 96.5% of net assets resolved to companies (CONTAINS edges with verbatim evidence, migration 0007). Issuer daily files not done; leveraged/derivative funds like TSLL understated (see connector README)
- [x] Daily prices connector. Massive prices + splits/dividends (migration 0006, ADR 0006); verified live for 2026-11-02 to 11-06, closes match E*TRADE. Backfilled 2026-11-07: about 499 days, 4.9M bars
- [x] Exposure by company / sector / country through ETFs. `python -m stockiq.graph`: funded look-through by company, SIC industry/division and country, plus economic exposure including swaps (TSLL: Tesla 99% of the portfolio, not 8.6%). Point-in-time tested; reconciles to the broker total. SIC is coarse (see sec_sic README); fund data is quarterly and stale (as-of dates shown)
**Ships:** exposure through your ETFs.
**Gate:** look-through totals reconcile to within 1% of real portfolio value.

## Phase 2 — Exposure X-ray
Supply-chain links and filing extraction were removed; see [ADR 0001](decisions/0001-remove-supply-chain-graph.md).
- [~] Resolver + review queue. Done: cascade (identifier, ticker, exact name, guarded trigram fuzzy) with confidence, review queue and CLI (`python -m stockiq.entities.review`), wired into N-PORT; VOO 98% of net assets resolved. Open: review page in the UI, LLM disambiguation step, precision gate
- [x] Concentration flags, Herfindahl (`python -m stockiq.xray`; Tesla 99.1% economic, effective number of companies 2.2). Signal rows wait for the Phase 4 table
- [x] Exposure view (replaced the Sankey; Cameron chose stacked bars 2026-11-08). Separate app in `frontend/` (React, TypeScript, plain SVG; ADR 0003). Redone 2026-11-07 as one drill-down chart: portfolio (by holding, or by company including swaps) → holding (stock, collateral, swaps owed, every company ranked) → filed evidence in a drawer; KPI tiles and flags above, caveats below. The companies, industries, countries and fund-remainder tables were removed. Run `make api` and `make frontend`. Checked in a browser against real data (light, dark, phone width); no component tests yet (only the data layer has unit tests)
- [~] Labelled ETF-holdings sample in tests/gold/resolution/. Done: 150-row sample with silver labels (OpenFIGI CUSIP to ticker to SEC company) and the evaluation (`python -m stockiq.entities.eval --source etf_holdings`): precision 100% on the 127 links scored. Open: Cameron reviews the labels (`reviewed` column) before the gate means anything
**Ships:** "what you're really exposed to".
**Gate:** entity-resolution precision on ETF holdings ≥ 90% on a labelled sample. **Paused by Cameron 2026-11-08:** waiting on his review of the gold labels and the review queue; resume with `python -m stockiq.entities.eval --source etf_holdings`.

## Phase 3 — Attribution + news feed
- [ ] Filing ingestion (10-K/10-Q/8-K) as documents for attribution
- [ ] Factor returns (French library), rolling loadings
- [ ] Daily attribution with look-through roll-up
- [ ] News ingest / cluster / tag / type
- [ ] Impact scoring, grounded explanations with citations
**Ships:** Home page with "why it moved" + second-order feed.
**Gate:** residual explanations cite a real item on most high-residual days (spot-check 20).

## Phase 4 — Alerts v1
- [ ] signal table, alerts service (score, dedupe, tier, cooldown, schedule)
- [ ] Discord/Telegram + email digest adapters
- [ ] Feedback buttons
**Ships:** you stop opening the app to check things.
**Gate:** < ~3 urgent alerts/week at chosen thresholds, most rated useful.

## Phase 5 — Event timeline + typical trends
- [ ] Calendars, event-study engine, portfolio event risk, timeline UI
**Gate:** point-in-time tests pass (no look-ahead in any event-study query).

## Phase 6 — Smart-money signals
- [ ] Form 4, 13F, short interest, congressional disclosures; cluster logic
**Gate:** historical lead/lag results recorded per signal type on your holdings.

## Phase 7 — Social sentiment
- [ ] Reddit, StockTwits, HN; attention z-scores, tone classifier, quality weighting, divergence detector
**Gate:** entity-resolution precision on social text ≥ 90% on a labelled sample.

## Phase 8 — Workflow-builder nodes + conditioning
- [ ] Expose modules as typed nodes in the trading platform; conditional event studies

## Later (out of v1)
Scenario/what-if engine · diversification/reallocation suggestions · thesis tracker · contribution sizing.

## Parking lot
Out-of-phase ideas noted while working go here instead of being built.

- Other derivatives in look-through: only swaps with a ticker reference are handled. Futures,
  options and forwards in N-PORT (`futureDeriv`, `optionSwaptionWarrantDeriv`, `forwardDeriv`),
  and swaps on indexes or baskets, are stored but not turned into exposure.
- Ticker history windows (blocker for Phase 3 and 5 return series, see ADR 0006): aliases have no
  real validity dates, so old price bars can attach to a ticker's current owner.
- Version holdings and cash like edges (known_at in the key). A corrected re-import of the same
  snapshot currently overwrites values and keeps the old `known_at`, so the correction looks
  known from the earlier time. Rare; matters once re-imports become routine.
- Route name-based fund-constituent matches (confidence 0.95) through the Phase 2 review queue;
  invariant 6 says anything under the accept threshold shouldn't go straight into the graph.
- Learned CUSIP/ISIN aliases inherit the name match's confidence (done); store it as a column
  once the resolver exists, instead of encoding it in the alias source.
- Funds held inside funds are counted as companies, not looked through.
- When the `signal` table lands (Phase 4), have the API read concentration flags from `signal`
  rows instead of calling the module directly, so there is one source of truth.
- Enforce "no edge without evidence" in the database (a deferred constraint) or with an invariant
  checker rule; today only the writers' convention does.
- Auth in front of the API (Tailscale or an auth proxy) before any frontend ships; it returns real
  holdings and has no login.
- Make `tests/gold/resolution/` cover more than VOO large caps (smaller, foreign and renamed
  companies, other ETFs) so the precision gate is not measured on the easy case.
- Arctic Shift connector (`connectors/arctic_shift/`) for Reddit, per ADR 0004. Needs Phase 1's
  entity and document tables. Fixtures already in `tests/fixtures/arctic_shift/`.
