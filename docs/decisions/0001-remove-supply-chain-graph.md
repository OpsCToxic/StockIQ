# 0001 — Remove the supply-chain graph and filing extraction

- **Status:** Accepted (recorded after the fact, 2026-11-02)
- **Date:** 2026-11-02

## Context
The first architecture draft built a supply-chain graph on top of holdings and ETF look-through. An
LLM would read 10-K and 10-Q filings and extract supplier, customer and geographic-revenue
relationships. Exposure then propagated up to two hops through those links.

The repo docs (docs/architecture.md, docs/roadmap.md) no longer include any of this. This ADR
records the removal so the roadmap link resolves. See "Entity resolution and the exposure graph"
in docs/architecture.md.

**The reasons below are my reading of the design, not a record of the discussion. Cameron should
correct them.**

## Options
| Option | Pros | Cons | Cost |
|---|---|---|---|
| Keep the supply-chain graph | Shows exposure that is hidden behind the companies you hold | Needs LLM extraction, a hand-labelled gold set, and a quality loop; many relationship weights are undisclosed, so exposure % looks more precise than it is | LLM spend on every new filing, plus labelling time |
| Remove it | Every number comes from sources with stated weights (brokerage, N-PORT, issuer files); fewer moving parts in v1 | No supplier, customer or geographic-revenue exposure | None |

## Decision
Remove the supply-chain graph and filing relationship extraction from v1.

Removed:
- Edge types SUPPLIES, SELLS_TO and REVENUE_FROM.
- The extraction pipeline, its quality loop and the `extractor_version` and `weight_disclosed` fields.
- Multi-hop exposure propagation, the two-hop cap, and "undisclosed supplier weights" as a risk.

Kept:
- 10-K, 10-Q and 8-K filings, ingested as documents to support attribution explanations. No
  relationships are extracted from them.
- Exposure through holdings and ETF look-through, rolled up to company, sector and country.
- "Supply disruption" as a news event type.

## Consequences
- Exposure X-ray (Phase 2) covers holdings, ETF contents, sectors and countries only. Its gate is
  entity-resolution precision on ETF holdings, not extraction precision.
- The `edge` table loses `weight_disclosed` and `extractor_version`.
- LLM spend drops: the LLM is used for explanations, relevance checks and entity disambiguation.
- The `llm-extraction` skill and the `extraction-engineer` agent were removed. The skill is
  replaced by `llm-explanations`, which covers explanations, relevance checks, caching and cost.

**Revisit if:** exposure through ETFs alone proves too shallow, and Cameron wants supplier or
customer links back. That would be a new phase and a new ADR.
