# etrade_csv

Imports the positions CSV from E*TRADE (Portfolio > Download). Manual, no API access needed.

- **Run:** `python -m stockiq.connectors.etrade_csv PATH [ACCOUNT_NAME]`. Needs Postgres, MinIO and
  the entity seed. Keep real exports in `data/` (git-ignored), never in `tests/fixtures/`.
- **Layout:** account summary, positions table (`Symbol, Last Price $, ..., Quantity, Price Paid $,
  ..., Total Gain $, Total Gain %, Value $`), a `CASH` row, a `TOTAL` row, and a footer
  `Generated at Nov 7 2026 07:57 PM ET`.
- **Point-in-time:** every row is `as_of` the footer time (America/New_York). `known_at` is the time
  we imported the file, so a later backtest never sees holdings before we had them.
- **Cost basis:** stored as total cost, `Value $ - Total Gain $`, which is exact to the cent.
  `Price Paid $` is rounded to 4 places, so quantity times price drifts by a few cents.
- **Cash:** goes to `cash_balance`, so portfolio totals reconcile with E*TRADE's.
- **Safety checks (the import aborts, nothing is written):** footer missing; positions plus cash do
  not equal the file's `TOTAL` (tolerance 5 cents); a symbol is not matched to exactly one
  entity by the resolver. Unmatched symbols are queued for review (`python -m
  stockiq.entities.review list`); accept the item with the right entity id and import again.
- **Idempotent:** the document key is the snapshot time plus a content hash; rows upsert on
  account, security and `as_of`. Re-importing the same file changes nothing.
- **Corrections:** re-importing a corrected file for the same snapshot overwrites values but keeps
  the first `known_at`; see the roadmap parking lot.
- **Limits:** no lots (the export has none), and no account number, so the account is named
  `All brokerage accounts` unless you pass a name. If the E*TRADE API connector later reports the
  same account, settle the double-counting rule in ADR 0002 first.
- **Fixture:** `tests/fixtures/etrade_csv/PortfolioDownload.csv` has the real layout with made-up
  symbols and numbers.
