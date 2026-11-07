# Portfolio Intelligence Platform — Architecture

This file is the source of truth for the architecture. It started as the Claude Doc "Portfolio
Intelligence Platform — Architecture" (https://claude.ai/artifact/MDKfJRebgEAqxDo1ad8T9i, 2026-11-01).
That doc is now an out-of-date snapshot: do not edit it, and if it disagrees with this file, this
file wins. An accepted ADR that changes the design updates this file in the same change.

## Overview

The platform shows what actually affects your money, including exposure you can't see from a
ticker list. It links your holdings, and everything inside your ETFs, to companies, sectors, and
countries. Every feature reads from that graph.

**Modules**
- **Exposure X-ray** — hidden concentration across holdings ("31% of your portfolio is one company once you look through your ETFs").
- **Second-order news feed** — news ranked by dollar impact on your portfolio, including companies you hold through ETFs.
- **Why did my portfolio move** — daily change split into market, sector, factor, and company-specific parts, with the news behind each.
- **Event timeline + typical trends** — upcoming earnings and macro releases, with historical behavior around similar events.
- **Social sentiment** — Reddit, StockTwits, Hacker News. Attention and tone tracked separately.
- **Smart-money signals** — insider trades (Form 4), institutional holdings (13F), short interest, congressional disclosures.
- **Alerts** — materiality-scored, tiered, deduplicated notifications with the exposure path explained.

**Non-goals for v1:** trade execution, scenario/what-if engine, reallocation suggestions,
contribution sizing, multi-user SaaS. The design leaves room for all of them.

**Operating constraint:** personal, non-commercial use. Reddit data comes from the free Arctic Shift
community archive (ADR 0004), not Reddit's own API, and market data avoids redistribution licensing.

## System architecture

```
Sources ──raw──▶ Object storage ──▶ Parse ──▶ Entity resolution ──▶ Graph + Store (Postgres)
                                                                        │
                                       Analytics modules ◀──────────────┤
                                              │ write                   │
                                              ▼                         │
                                         signal table                   │
                                              │                         │
                                       Alerts service ──▶ delivery      │
                                                                        ▼
                                                      API ──▶ dashboard + workflow-builder nodes
```

Modules never notify you themselves; that keeps alert logic in one place.

## Data sources and ingestion

Every source gets its own connector worker that writes raw payloads to object storage first, then
emits a normalized event. Raw-first means history can be re-parsed when a parser improves.

| Source | Feeds | Cadence | Cost / limits | Notes |
|---|---|---|---|---|
| Brokerage aggregator (SnapTrade or Plaid Investments) | Holdings, lots, transactions | Daily + on demand | Paid per connection | CSV import as fallback |
| E*TRADE API (direct sign-on) | Holdings, lots | Daily, after sign-on | Cost unconfirmed; token expires midnight ET, so login is daily | Read endpoints only; see ADR 0002 |
| SEC EDGAR N-PORT | ETF / fund holdings for look-through | Quarterly, ~60-day lag | Free; descriptive User-Agent, ~10 req/s | Issuer daily files fresher where available |
| SEC EDGAR 10-K / 10-Q / 8-K | Filing text attached to attribution explanations | On filing | Free | Stored as documents; no relationships extracted |
| SEC EDGAR Form 4 | Insider trades | ~2 business days after trade | Free | Use daily index files, not crawling |
| SEC EDGAR 13F | Institutional long positions | Quarterly, ≤45 days after quarter end | Free | Long US equity only, managers > $100M |
| FINRA | Short interest | Twice monthly | Free | Pair with daily short-volume data |
| House Clerk / Senate eFD | Congressional trades | Up to ~45 days | Free | Some PDFs scanned; amounts are ranges |
| Massive (formerly Polygon; ADR 0005) | Daily prices, corporate actions | EOD; one grouped-daily call per date covers all tickers | Free: 5 calls/min, 2 years of history; paid tiers for 5–10+ years | Store unadjusted prices + splits/dividends and adjust ourselves (point-in-time); upgrade when history is the limit |
| Kenneth French data library | Factor returns | Monthly / daily | Free | Used by attribution |
| Calendars | Earnings, ex-div, FOMC, CPI, jobs, OPEX, index rebalances | Daily refresh | Mostly free + market-data API | Earnings dates shift; re-check daily |
| News API (Benzinga, Polygon news, RSS) | Headlines with tickers | Stream / 5-min poll | Paid for full text | Store URL + summary, not full articles |
| Arctic Shift API (community Reddit archive; ADR 0004) | Investing subreddit posts/comments | Poll ~15 min, page by `after` | Free, no key; dynamic rate limit, no uptime guarantee; terms unstated | New items lag minutes; `score` / `num_comments` final after ~36h, so re-fetch; keep raw for history; honour removals |
| StockTwits API | Cashtag streams, bull/bear tags | Poll | Rate-limited | Bull/bear tags = free sentiment labels |
| Hacker News (Firebase API) | Tech discussion | Poll | Free | Tech names |
| Earnings call transcripts | Management language | Quarterly | Usually paid | Optional, later phase |

**Connector contract:** `fetch(since) -> raw[]`, `parse(raw) -> records[]`, publish
`source.<name>.ingested` events. Shared library: token-bucket rate limiting per source, retries
with backoff, cursor/checkpoint storage, idempotent upserts keyed on the source's own ID.

**Scheduling:** batch jobs (filings, 13F, short interest, calendars) in the workflow scheduler;
pollers (news, Reddit, StockTwits, intraday prices) as long-lived workers.

## Entity resolution and the exposure graph

The graph is the core asset; entity resolution is its hardest part.

### Entity resolution
- **Canonical ID:** one `entity_id` per company, mapped to CIK, CUSIP, FIGI, LEI, current and historical tickers, name variants.
- **Seed:** SEC company tickers file + OpenFIGI. Private companies get entities too (`public = false`).
- **Resolver:** exact identifier match → alias table → trigram fuzzy match → LLM disambiguation with context. Output carries a confidence score.
- **Social text:** cashtags first; bare-word tickers (AI, ALL, NOW, IT) only with a cashtag, company name, or finance context nearby. Keep a stop-list.
- **Review queue:** low-confidence matches go to a review UI; decisions become aliases.

### Graph schema
Nodes: Company, Fund, Portfolio, Account, Sector, Country/Region, Person, Institution.
Edges are time-stamped (`valid_from` / `valid_to`):

| Edge | Example | Weight | Source |
|---|---|---|---|
| HOLDS (portfolio → security) | You → VOO | Market value | Brokerage |
| CONTAINS (fund → company) | VOO → AAPL | Fund weight % | N-PORT / issuer file |
| IN_SECTOR | AAPL → Tech hardware | 1 | GICS-like mapping |
| INSIDER_OF / TRADED | Exec → company | Trade size | Form 4 |
| POSITION_IN (institution → company) | Manager → MSFT | Shares, value | 13F |

**Provenance rule:** no edge without a citation to its source.

### Exposure propagation
Exposure to a company = Σ over paths of holding value × fund weight, so a direct holding counts at
full value and an ETF position at its look-through share. Sector and country exposure roll up from
those company totals, using each company's own sector and country.

## Storage and data model

Postgres as system of record, with extensions instead of a zoo of databases.

| Store | Holds | Why |
|---|---|---|
| Postgres | Entities, holdings, edges, events, alerts, config | One source of truth; plain joins handle look-through at personal scale |
| TimescaleDB | Prices, factor returns, sentiment/attention series | Time-bucketed queries |
| pgvector | Embeddings of filing chunks, news, posts | Semantic search, dedupe, clustering |
| S3 / MinIO | Raw payloads | Reprocessing without re-fetching |
| Redis | Cache, rate-limit buckets, Redis Streams | Cheap event bus |

Graduation path: Kafka/Redpanda if event volume outgrows Redis Streams. Event schema doesn't change.

### Core tables
- `entity(id, name, type, cik, figi, lei, public, sector_id, country)`
- `entity_alias(entity_id, alias, kind, source, valid_from, valid_to)`
- `account(id, broker, name)` · `holding(account_id, security_id, qty, cost_basis, as_of)` · `lot(...)`
- `edge(id, src_id, dst_id, type, weight, valid_from, valid_to, confidence)`
- `edge_evidence(edge_id, doc_id, section, span_text, url)`
- `document(id, source, kind, url, published_at, raw_uri, hash)`
- `document_entity(doc_id, entity_id, confidence, sentiment, relevance)`
- `price_bar(security_id, ts, o, h, l, c, v)` (hypertable)
- `factor_return(factor, date, ret)` · `factor_loading(security_id, factor, beta, window_end)`
- `calendar_event(id, entity_id?, type, scheduled_at, confirmed, source)`
- `event_study(entity_id, event_type, window, n, mean_ret, median_ret, p25, p75, computed_at)`
- `social_metric(entity_id, source, bucket_ts, mentions, mention_z, bull_ratio, unique_authors)` (hypertable)
- `insider_trade(...)` · `inst_position(...)` · `short_interest(...)` · `congress_trade(...)`
- `signal(id, module, kind, entity_id, ts, strength, payload_json)` — every module's output, one shape
- `alert(id, signal_ids[], tier, materiality, exposure_path_json, status, delivered_at, feedback)`

**Point-in-time rule:** every fact stores when it became known separately from when it happened.
Backtests and event studies query by known-time only.

## Analytics modules

Each module reads graph + time series and writes rows to `signal`. Modules never call each other
or send notifications.

### Exposure X-ray
Dollar and % exposure to every company, sector, and country. Flags any node
above a threshold (e.g. 10%) and computes Herfindahl across top-level companies. Runs nightly and on
holdings/edge changes. Output: exposure table + Sankey/sunburst.

### Attribution ("why did my portfolio move")
1. Rolling 252-day regression of each holding on market, sector, size, value, momentum.
2. Daily decomposition into factor contributions + residual.
3. Roll up to the portfolio with look-through ETF weights.
4. For the largest residuals, attach news/filings from the window (high-relevance `document_entity`), ranked by an LLM relevance check.
5. LLM writes a 3-sentence explanation only from retrieved items, citing them.

### Event timeline + typical trends
- Timeline: `calendar_event` rows for holdings and fund constituents above a weight cutoff; macro applies to all.
- Event studies: abnormal returns (minus market-model expected) from day −10 to +10 over past occurrences; store n, mean, median, IQR.
- Conditioning (v2): split by context (pre-event IV, sentiment spike, insider buying).
- Portfolio event risk: % of exposure with an event in the next 5/10/30 days.
- Guardrails: show n and spread; grey out n < 8; never phrase averages as predictions.

### Social sentiment
Dedupe (embedding similarity + author/time) → resolve entities → attention (mentions and unique
authors per hour as a z-score vs. the entity's own 30-day baseline) → tone (FinBERT-style
classifier trained partly on StockTwits tags; LLM only for spot checks) → quality weighting (new
accounts, low karma, near-duplicate bursts) → per-entity lead/lag test, reporting "no measurable
edge" where true.

### Smart-money signals
- Form 4: separate open-market buys (code P) from sells, exercises, 10b5-1 trades; cluster buys = 3+ insiders within 30 days.
- 13F: QoQ holder-count and share changes; new positions from a chosen manager watchlist.
- Short interest: level, days-to-cover, change vs. prior; flag large jumps.
- Congress: parse, resolve, evaluate returns from the **disclosure date**.
- Divergence detector for social tone vs. insider/institutional direction.

## News pipeline and second-order feed
Ingest (URL, headline, source, timestamp, short summary) → dedupe/cluster (48h embedding window) →
entity tagging above a relevance score → event typing (guidance, M&A, litigation, product, supply
disruption, labor, regulatory, macro) → exposure join (direct + ETF look-through) → score
`impact = exposure_dollars × severity × novelty × source_credibility` → explain with exposure path
and a one-line "why this matters to you". High-impact items emit signals.

## Alerts service
Consume signals → enrich with exposure path → score → dedupe/merge → tier → schedule → deliver →
record feedback.
- Materiality = exposure_weight × signal_strength × novelty × category_weight (weights tuned by feedback).
- Tiers: **Urgent** push in real time · **Notable** daily pre-market digest · **FYI** in-app only.
- Dedupe by entity + story cluster window; per-entity/category cooldowns; quiet hours + market awareness.
- Every alert carries exposure path, triggering signals, source links.
- Custom rules from the workflow builder (e.g. `insider_cluster_buy AND attention_z < 0 → urgent`).
- Delivery adapters implement `send(alert, tier)`: email, Discord/Telegram, ntfy/web push.

## API, frontend, workflow builder
FastAPI REST + WebSocket:
- `GET /portfolio/exposure` · `GET /portfolio/attribution?date=` · `GET /feed?since=`
- `GET /timeline?from=&to=` · `GET /entities/{id}` · `GET /signals?module=&entity=`
- `GET/POST /alerts` · `POST /alerts/{id}/feedback` · CRUD `/rules` · `WS /stream`

Pages: Home, Exposure (Sankey with clickable evidence), Timeline, Entity, Alerts inbox, Review queue.

Workflow-builder nodes (trading platform): Sources (Holdings, Entity Signals, News Feed, Calendar),
Transforms (Exposure Filter, Event Study, Sentiment Z-Score, Insider Cluster), Logic (Threshold,
AND/OR, Cooldown), Sinks (Alert, Digest, Webhook). Nodes call the same API.

## Tech stack
| Layer | Choice | Alternatives |
|---|---|---|
| Language | Python 3.12 | — |
| API | FastAPI + Pydantic | Litestar |
| Batch orchestration | Dagster | Prefect, Airflow |
| Workers | async workers on Redis Streams | Celery, Arq |
| Database | Postgres 16 + TimescaleDB + pgvector | — |
| Bus | Redis Streams | Redpanda/Kafka |
| Object storage | MinIO / S3 | R2 |
| Analytics | pandas/Polars, statsmodels, NumPy | DuckDB |
| NLP | FinBERT-style classifier, sentence-transformers | — |
| LLM | Claude API with prompt caching | smaller model for volume |
| Frontend | React + TypeScript + ECharts/D3 (ADR 0003) | Plotly |
| Notifications | Discord/Telegram, SMTP, ntfy | web push |
| Infra | Docker Compose on home server / small VM | k8s only if multi-user |
| Observability | structured logs, Prometheus + Grafana | Sentry |

## Security, compliance, cost
- Secrets in a secrets manager or SOPS-encrypted env; never plaintext in DB or logs. Read-only brokerage scopes.
- Expose over Tailscale or behind an auth proxy. Encrypt DB backups.
- Respect API terms (Reddit content personal and non-commercial; Arctic Shift states no terms, see ADR 0004; market-data no redistribution, SEC User-Agent + rate limits). No prohibited scraping. Store summaries + links, not articles.
- LLM only on pre-filtered items, cached by document hash + prompt version. Monthly budget caps per paid API.

## Risks
| Risk | Mitigation |
|---|---|
| Wrong entity matches | Confidence scores, review queue, gold-set precision gates |
| Stale fund holdings | Prefer issuer daily files; show as-of dates |
| Look-ahead bias | Known-time queries only; automated PIT tests |
| Small-sample patterns | Show n and spread; grey out n < 8 |
| Alert fatigue | Materiality, tiers, cooldowns, feedback |
| API terms/pricing changes | Connector isolation; raw-first; alternates listed |
| LLM cost creep | Hash-keyed caching, pre-filtering, budget alerts |

## Open questions (Cameron decides)
- ~~Market-data provider~~ Decided: Massive free for the PoC (ADR 0005).
- Brokerage aggregator, and broker support.
- E*TRADE read-only access: if no read-only key exists, whether to approve an exception (ADR 0002).
- Dashboard as a separate app or pages inside the trading platform.
- 13F manager watchlist.
