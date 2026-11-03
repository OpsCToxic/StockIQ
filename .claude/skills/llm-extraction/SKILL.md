---
name: llm-extraction
description: How StockIQ uses the Claude API to extract supplier/customer/geographic-revenue relationships from SEC filings with provenance, caching, versioning, and gold-set evaluation. Use for any LLM extraction, classification, or explanation code.
---

# LLM extraction (filings → edges)

## Pipeline
1. **Split** 10-K/10-Q into sections: Item 1 (Business), 1A (Risk Factors), 7 (MD&A), segment and
   concentration notes.
2. **Filter** cheaply before any LLM call: keyword hits (customer, supplier, sole source,
   concentration, "accounted for", %, region names) + embedding similarity against seed passages.
   Only passing chunks go to the LLM.
3. **Extract** with a strict JSON schema (use tool use / structured output, not free text):
```json
{
  "relationships": [{
    "counterparty_name": "string",
    "relationship": "SUPPLIES | SELLS_TO | REVENUE_FROM",
    "direction": "counterparty_to_filer | filer_to_counterparty",
    "share_pct": "number | null",
    "share_basis": "revenue | cogs | purchases | null",
    "evidence_span": "verbatim sentence(s) from the chunk",
    "confidence": "0..1"
  }]
}
```
   The prompt must say: only extract relationships stated in the text; `evidence_span` is copied
   verbatim; if a share isn't stated, `share_pct` is null (never estimate).
4. **Verify** that `evidence_span` is a substring of the chunk (normalised whitespace). Drop items
   that fail.
5. **Resolve** `counterparty_name` via the resolver (see `entity-resolution` skill).
6. **Write** `edge` + `edge_evidence` in one transaction: accession number, section, span, URL,
   `extractor_version`, confidence, `weight_disclosed = share_pct is not None`, `valid_from` = filing
   period start, `known_at` = filing acceptance time.
7. **Diff** against the previous filing from the same filer: new / dropped / changed relationships
   become `signal` rows (module `graph`).

## Versioning and cache
- `EXTRACTOR_VERSION` in `graph/extraction.py` = semver; bump on any prompt, schema, model, or filter change.
- Cache key = `sha256(chunk_text) + EXTRACTOR_VERSION`. Never re-call the LLM for a cached key.
- Use prompt caching for the system prompt + schema (identical across calls).
- Model choice lives in config, not code. Use the cheaper model for high-volume classification.

## Evaluation
- Gold set: `tests/gold/extraction/*.jsonl` — `{chunk, expected: [relationships]}`, ~200 items,
  hand-labelled by Cameron.
- `uv run python -m stockiq.graph.eval` reports precision, recall, and per-relationship-type scores,
  appending to `tests/gold/results.csv` with the extractor version.
- Phase 2 gate: precision ≥ 90%. Never lower precision silently.

## Explanations (attribution, feed)
LLM-written explanations use only retrieved documents passed in the prompt, cite them by id, and
say so when nothing relevant was found. No outside knowledge, no predictions.
