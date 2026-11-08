# 0003 — React frontend, Python backend

- **Status:** Accepted
- **Date:** 2026-11-02

## Context
The stack left the frontend undecided ("match the trading platform: React or Vue"). Cameron also
considered a Go backend. See "Tech stack" in docs/architecture.md.

The analytics work is the bulk of the backend: rolling regressions (statsmodels), event studies
(pandas/Polars), a FinBERT-style classifier and sentence-transformers, and Dagster batch jobs. All
of these are Python. At personal scale the polling and API load do not need Go.

## Options
| Option | Pros | Cons | Cost |
|---|---|---|---|
| Python backend, React frontend | One backend language; React matches the trading platform; typed client from FastAPI's OpenAPI spec | Two languages overall (Python and TypeScript) | Free |
| Go for pollers/API, Python for analytics | Cheap concurrency for pollers | Second backend toolchain; schema kept in sync across two languages; invariant checks and hooks rebuilt for Go | Extra build and maintenance time |
| Go for everything | One language | No equivalent of the Python analytics and NLP libraries | Rewrite of the plan |

## Decision
Python for the backend (FastAPI), React for the frontend. Go is not adopted.

## Consequences
- The frontend is React with TypeScript, with ECharts or D3 for charts. Generate the API client
  from FastAPI's OpenAPI spec so request and response types stay in sync.
- The frontend lives outside `src/stockiq/` so the Python tooling (ruff, mypy, the invariant
  checker) does not touch it. Add a `frontend/` folder when the first page is built.
- **Decided 2026-11-08 (Cameron): the dashboard is a separate app** in `frontend/`, not pages inside
  the trading platform. The workflow-builder nodes in the trading platform still call the same API.
- No frontend work starts before the roadmap reaches it. The first screen is the Exposure page
  (Phase 2).

**Revisit if:** profiling shows a Python poller is too slow or too heavy, in which case move only
that poller to Go (it only writes raw data and publishes events), or if StockIQ becomes multi-user.
