# StockIQ

Personal portfolio intelligence platform: a supply-chain exposure graph over your holdings (and
what's inside your ETFs), with "why did my portfolio move" attribution, a second-order news feed,
an event timeline with typical trends, social sentiment, smart-money signals, and alerts.

- Design: [docs/architecture.md](docs/architecture.md)
- Build order and gates: [docs/roadmap.md](docs/roadmap.md)
- Working with coding agents: [AGENTS.md](AGENTS.md) (Claude Code: [CLAUDE.md](CLAUDE.md))

## Quick start
```bash
cp .env.example .env      # fill in POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD, SEC_USER_AGENT, …
make up                   # Postgres (Timescale + pgvector), Redis, MinIO
make install              # uv sync
make lint test
```

## Claude Code harness
| Piece | Where | What it does |
|---|---|---|
| Agent rules | `AGENTS.md` | Tool-neutral scope, invariants, stack, layout, commands, workflow |
| Claude memory | `CLAUDE.md` | Imports AGENTS.md; adds skills, subagents, commands, hooks |
| Subagents | `.claude/agents/` | `quant-reviewer`, `architecture-reviewer`, `connector-engineer`, `extraction-engineer` |
| Skills | `.claude/skills/` | `new-connector`, `llm-extraction`, `entity-resolution`, `point-in-time`, `event-study` |
| Commands | `.claude/commands/` | `/phase`, `/gate`, `/new-connector`, `/review`, `/adr` |
| Hooks | `.claude/settings.json` | Block edits to secrets, raw payloads, committed migrations; format Python and check invariants after edits |
| Guardrails | `scripts/check_invariants.py` | Module boundaries, no wall clock in analytics, no hard-coded secrets (also runs in CI) |

Personal, non-commercial use. Not investment advice.
