# CLAUDE.md — StockIQ

@AGENTS.md

## Claude Code specifics
The shared rules above apply. This section covers Claude-only tooling in `.claude/`.

**Skills** — load before the matching work:
- `new-connector`: anything under `src/stockiq/connectors/`
- `entity-resolution`: resolver, entity tagging
- `llm-explanations`: LLM explanations, relevance checks, classification
- `point-in-time` + `event-study`: time series, backtests, event studies, lead/lag tests

**Subagents**
- `quant-reviewer`: after changing analytics or time-series SQL (look-ahead, survivorship, small-n)
- `architecture-reviewer`: before merging a feature or planning cross-package work
- `connector-engineer`: delegate connector work

**Commands**: `/phase`, `/gate <n>`, `/new-connector <source>`, `/review`, `/adr <title>`

**Hooks** (`.claude/settings.json`): edits to secrets, `data/raw/`, and committed migrations are
blocked; after each Python edit, ruff formats the file and the invariant checker runs — fix any
violation it reports rather than suppressing it, unless Cameron agrees to an
`# invariant: allow INV-XXX <reason>` comment.
