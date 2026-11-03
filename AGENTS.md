# AGENTS.md — StockIQ

Instructions for any coding agent (Claude Code, Codex, Cursor, …) working in this repo.
Claude-specific tooling lives in CLAUDE.md.

## Project

Personal tool that shows what actually affects Cameron's money, including hidden connections.
Holdings (and everything inside ETFs) are linked to suppliers, customers, and geographies in a
**supply-chain graph**. Every feature reads from that graph.

Full design: @docs/architecture.md · Build order and gates: @docs/roadmap.md

## Modules
Exposure X-ray · Second-order news feed · "Why did my portfolio move" attribution ·
Event timeline + typical trends · Social sentiment · Smart-money signals · Alerts.

Non-goals for v1: trade execution, scenario/what-if engine, reallocation suggestions,
contribution sizing, multi-user SaaS. Do not build these unless asked.

## Non-negotiable invariants
These are the rules that make the numbers trustworthy. Break one only if Cameron explicitly says so.

1. **No edge without evidence.** Every graph edge has an `edge_evidence` row: doc id, section,
   verbatim span, URL, extractor version, confidence. Undisclosed weights are stored with
   `weight_disclosed = false` and shown as "undisclosed", never hidden.
2. **Point-in-time.** Every fact stores when it became known (`known_at` / `published_at` /
   `ingested_at`) separately from when it happened. Backtests, event studies, lead/lag tests and
   attribution query by known-time only. No look-ahead.
3. **Modules only write signals.** Analytics modules read the store and write rows to `signal`.
   They never import each other, never call delivery adapters, never notify. The alerts service
   is the only thing that turns signals into notifications. (Enforced by `scripts/check_invariants.py`.)
4. **Raw-first ingestion.** Connectors write the raw payload to object storage before parsing,
   then upsert idempotently keyed on the source's own ID. Re-parse from raw, don't re-fetch.
5. **Honest statistics.** Every event-study / pattern output carries `n` and spread. Patterns with
   n < 8 are greyed out. Never phrase historical averages as predictions. Where lead/lag shows no
   edge, say "no measurable edge".
6. **Entity resolution confidence.** Resolver output always carries a confidence score; low
   confidence goes to the review queue, not straight into the graph. Bare-word tickers
   (AI, ALL, NOW, IT…) only count with a cashtag, company name, or finance context nearby.
7. **Terms and secrets.** SEC requests send a descriptive User-Agent and stay ≤ 10 req/s.
   Reddit is non-commercial free tier. Store news summaries + links, not full articles. No HTML
   scraping where terms forbid it. Brokerage scopes are read-only. Secrets live in `.env`
   (git-ignored) or a secrets manager — never in code, the DB in plaintext, or logs.
8. **LLM cost control.** LLM calls run only on pre-filtered chunks, are cached by
   `document hash + extractor version`, and use prompt caching for repeated instructions.
   High-volume classification uses the small classifier, not the LLM.

## Stack
Python 3.12 (uv) · FastAPI + Pydantic · Dagster (batch) · async workers on Redis Streams ·
Postgres 16 + TimescaleDB + pgvector · Redis · MinIO/S3 · pandas/Polars, statsmodels ·
Hugging Face (FinBERT-style), sentence-transformers · Claude API · Docker Compose.
Frontend is undecided (match the trading platform: React or Vue) — ask before choosing.

## Layout
```
src/stockiq/
  core/        config, db session, logging, event bus, shared types
  connectors/  one package per source; shared rate limit/retry/cursor lib in connectors/base.py
  entities/    entity master, alias table, resolver, review queue
  graph/       edge model, filing extraction pipeline, exposure propagation
  modules/     exposure/, attribution/, timeline/, sentiment/, smart_money/, news/  (signal writers)
  alerts/      scoring, dedupe, tiers, scheduling, delivery adapters
  api/         FastAPI app, routers, websocket stream
  orchestration/ Dagster definitions
migrations/    Alembic
tests/         unit/, integration/, pit/ (point-in-time tests), gold/ (extraction gold set)
docs/          architecture.md, roadmap.md, decisions/ (ADRs)
```

## Commands
```
make up            # docker compose: postgres(timescale+pgvector), redis, minio
make install       # uv sync
make test          # pytest (unit + pit)
make lint          # ruff check + ruff format --check + mypy + invariants
make invariants    # scripts/check_invariants.py
make migrate       # alembic upgrade head
make gate PHASE=N  # run the phase gate checks listed in docs/roadmap.md
```

## How to work here
- Find the current phase in `docs/roadmap.md` before starting. Stay inside it; note anything
  out-of-phase in the roadmap's parking lot rather than building it.
- Schema changes go through an Alembic migration; never edit tables by hand or edit a committed migration.
- Never edit `.env`, `secrets/`, or anything under `data/raw/` (raw payloads are immutable).
- Significant design choices (provider picks, schema shape, graduating to Neo4j/Kafka) get an
  ADR in `docs/decisions/` using the template there.
- Connectors follow the contract in `docs/architecture.md` (raw first, idempotent upsert, rate limits).
- Every connector has a parse test against a saved raw fixture in `tests/fixtures/`.
  Every analytics query that touches time has a test in `tests/pit/`.
- Run `make lint test` (includes `scripts/check_invariants.py`) before saying work is done.
  Report failures honestly.
- Open questions from the architecture (market-data provider, brokerage aggregator, dashboard
  placement, 13F watchlist, hop cap) are Cameron's calls — ask, don't decide.
