# 0002 — Add E*TRADE sign-on for holdings import

- **Status:** Superseded 2026-11-08. Cameron dropped the E*TRADE API connector; positions come
  from the CSV export (`connectors/etrade_csv`). Kept for the record; do not build the connector
  unless he reopens it, and the read-only question below would need answering first.
- **Date:** 2026-11-02

## Context
Holdings come from a brokerage source (see "Data sources and ingestion" in docs/architecture.md).
The plan was CSV import first, then an aggregator. Cameron chose to add a direct E*TRADE sign-on as
an additional source. It does not replace either of those.

What E*TRADE's API docs say:
- View Portfolio returns quantity, cost basis, market value, and tax lots (`lotsRequired=true`).
- Auth is OAuth 1.0a. Access tokens expire at midnight US Eastern, and the user must then log in
  again. Renewal only reactivates a token that has been idle for two hours.
- The API also covers order placement.

## Options
| Option | Pros | Cons | Cost |
|---|---|---|---|
| CSV import | No broker connection; simple | Manual; limited to what the export includes | Free |
| E*TRADE sign-on | Direct; no third party; includes lots | E*TRADE only; daily login; OAuth 1.0a | Unconfirmed |
| Aggregator | Unattended sync; multiple brokers | Third party holds access | Paid per connection |

## Decision
Add E*TRADE sign-on alongside CSV import and the aggregator. The aggregator choice stays open and
is on hold (Cameron, 2026-11-02), so E*TRADE direct and CSV are the only sources for the proof of
concept. The E*TRADE developer platform is stated to be free (developer.etrade.com FAQ; confirm
current terms when requesting keys).

## Consequences
- Add an E*TRADE connector in Phase 1, following the standard contract: raw first, idempotent upsert.
- The connector calls read endpoints only and never calls order endpoints.
- Add a daily sign-on step. If it is skipped, keep the last snapshot and show its as-of date.
- Keep tokens and keys in `.env` or a secrets manager, never in the DB in plaintext or in logs.
- If E*TRADE and another source both report the same account, a rule is needed to avoid double
  counting. Settle this before enabling both for one account.

**Status 2026-11-08:** Cameron has an E*TRADE **sandbox** key. Sandbox returns canned data, so it
can build and test the connector but cannot show his real holdings. Real holdings come from the CSV
export until a production key is approved.

**Open before Phase 1 build:**
- Invariant 7 requires read-only brokerage scopes. No read-only key option has been found for
  E*TRADE. If none exists, Cameron must approve an exception.
- Production key requirements and any cost for an individual are unconfirmed.
- The transactions endpoint has not been reviewed.

**Revisit if:** the daily login proves impractical, or StockIQ needs brokers beyond E*TRADE.
