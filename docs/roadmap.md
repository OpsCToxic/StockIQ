# Roadmap

Build the graph first; every module depends on it. Each phase ends with something usable daily and a
**gate** that must pass before the next phase starts. `make gate PHASE=N` runs the automated part.

**Current phase: 0 (harness + skeleton)**

Status keys: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Phase 0 — Harness + skeleton
- [x] Claude Code harness (CLAUDE.md, agents, skills, commands, hooks)
- [x] Docker Compose (Postgres+Timescale+pgvector, Redis, MinIO), Makefile, CI
- [x] Alembic initialised, first empty migration (applied locally, revision 0001)
- [ ] Apply for Reddit Data API access now (2–4 week approval wait)
- [ ] Decide market-data provider → ADR
- [ ] Decide brokerage aggregator → ADR
- [ ] Request E*TRADE sandbox key; resolve open questions in [ADR 0002](decisions/0002-etrade-sign-on.md)
**Gate:** `make up && make lint test` green in CI.

## Phase 1 — Foundation: holdings + look-through
- [ ] Core tables: entity, entity_alias, account, holding, lot, document, price_bar
- [ ] Entity master seed: SEC company tickers + OpenFIGI
- [ ] Brokerage import: CSV first, aggregator second
- [ ] E*TRADE sign-on connector with daily login (read endpoints only)
- [ ] N-PORT fund holdings connector (issuer daily files where available)
- [ ] Daily prices connector
- [ ] Exposure by company / sector / country through ETFs
**Ships:** exposure through your ETFs.
**Gate:** look-through totals reconcile to within 1% of real portfolio value.

## Phase 2 — Exposure X-ray
Supply-chain links and filing extraction were removed; see [ADR 0001](decisions/0001-remove-supply-chain-graph.md).
- [ ] Resolver + review queue
- [ ] Concentration flags, Herfindahl
- [ ] Sankey view
- [ ] Labelled ETF-holdings sample in tests/gold/resolution/
**Ships:** "what you're really exposed to".
**Gate:** entity-resolution precision on ETF holdings ≥ 90% on a labelled sample.

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
