---
name: entity-resolution
description: Rules for mapping tickers, cashtags, CIK/CUSIP/FIGI, and company names (from filings, ETF holdings, news, and social posts) to StockIQ entity_ids with confidence and a review queue. Use for any resolver, alias, or entity-tagging code.
---

# Entity resolution

Every downstream number is wrong if a mention lands on the wrong node. Precision first.

## Canonical model
- One `entity.id` per company (public or private), mapped to CIK, CUSIP, FIGI, LEI.
- `entity_alias(entity_id, alias, kind, source, valid_from, valid_to)` holds tickers (current and
  historical), name variants, and reviewed aliases. Tickers get reused — always respect validity windows
  and resolve as of the document's `known_at`.
- Seed from the SEC company tickers file + OpenFIGI.

## Resolver cascade (stop at first confident hit)
1. Exact identifier (CIK, CUSIP, FIGI, LEI) → confidence 1.0
2. Exact alias match valid at `as_of` → 0.95
3. Trigram fuzzy name match (pg_trgm) above threshold, with legal-suffix normalisation
   (Inc, Corp, Ltd, Co., plc, N.V., Holdings) → similarity-scaled
4. LLM disambiguation with surrounding context and the top-k candidates → model confidence, capped at 0.9
Every result returns `(entity_id | None, confidence, method)`.

## Thresholds
- ≥ 0.9: accept.
- 0.6–0.9: accept provisionally **and** enqueue for review.
- < 0.6: do not link; enqueue.
Review decisions become `entity_alias` rows (`source = "review"`), so the resolver improves.

## Social and news text
- Cashtags (`$NVDA`) first.
- Bare-word tickers count only with a cashtag, company name, or finance context nearby.
  Maintain `entities/ambiguous_tickers.txt` (AI, ALL, NOW, IT, ON, ARE, CAN, SO, BE, GO, …).
- Relevance score per mention; passing mentions below the threshold don't create `document_entity`.

## Tests
Labelled samples in `tests/gold/resolution/` for filings, ETF holdings, news, and social text.
Phase 7 gate: ≥ 90% precision on social text.
