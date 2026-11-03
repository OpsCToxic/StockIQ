---
name: llm-explanations
description: How StockIQ uses the Claude API for explanations, relevance checks, and disambiguation, with grounding, citations, caching, and cost control. Use for any LLM explanation, relevance, classification, or disambiguation code.
---

# LLM explanations

The LLM writes or ranks text from items we already retrieved. It does not add facts. Filings are
stored as documents; no relationships are extracted from them (ADR 0001).

## Where the LLM is used
- **Attribution explanations:** a 3-sentence explanation of a large residual, from retrieved
  news and filings in the window.
- **Relevance checks:** rank retrieved items by how well they explain a move.
- **Entity disambiguation:** last step of the resolver (see the `entity-resolution` skill).
- **Spot checks** of sentiment output. High-volume classification uses the small classifier.

## Grounding rules
- Pass only retrieved documents in the prompt. Cite them by document id in the output.
- Say so when nothing relevant was found. Do not fill the gap from outside knowledge.
- No predictions and no advice. Describe what happened and what the sources say.
- Check that every cited id was in the prompt. Drop or flag output that cites anything else.

## Caching and cost
- Run the LLM only on items that already passed a cheap filter (keyword, embedding, or relevance score).
- Cache key = `sha256(document text) + PROMPT_VERSION`. Never re-call the LLM for a cached key.
- Bump `PROMPT_VERSION` (semver) on any change to the prompt, output schema, model, or filter.
- Use prompt caching for the system prompt and any schema, which are identical across calls.
- Model choice lives in config, not code.
- Set monthly budget caps per paid API and alert when volume spikes.

## Structured output
Use tool use or structured output with a strict schema, not free text, wherever the result is
parsed by code. Validate it before storing.

## Evaluation
- Spot-check explanations by hand: for the Phase 3 gate, residual explanations must cite a real
  item on most high-residual days (check 20).
- Keep a small labelled set for relevance ranking and disambiguation. Report results by prompt
  version, and do not ship a version that lowers precision.
