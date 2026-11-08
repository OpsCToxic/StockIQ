# sec_tickers

Seeds the entity master from SEC's ticker files. Batch, daily is plenty.

- **Endpoints:** `https://www.sec.gov/files/company_tickers_exchange.json` (cik, name, ticker,
  exchange) and `https://www.sec.gov/files/company_tickers_mf.json` (cik, seriesId, classId, symbol).
- **Auth:** none, but SEC fair access needs a descriptive `User-Agent` with a contact email. Set
  `SEC_USER_AGENT` in `.env`; the client refuses to run without an `@` in it.
- **Rate limit:** 5 req/s here (SEC allows 10). The connector makes two requests per run.
- **Terms:** public data. No redistribution concern, but keep the User-Agent honest.
- **Companies:** one entity per CIK. Share classes (GOOG/GOOGL) become extra ticker aliases.
- **Funds:** one entity per series id; the trust CIK goes in `filer_cik`. The file has no fund
  names, so the ticker stands in as `name` until the N-PORT connector sets the series name.
- **Point-in-time:** the files carry no history. Aliases open at fetch time and close when a ticker
  leaves the file, so a reused ticker resolves to the right company going forward. Documents known
  before the first seed cannot be resolved by ticker alias.
- **Fixtures:** `tests/fixtures/sec_tickers/` are real payloads from the 2026-11-08 run, trimmed
  to a handful of tickers.
- **Run:** `python -m stockiq.connectors.sec_tickers` (needs `.env` loaded, Postgres and MinIO up).
  First run: 8,009 companies, 12,303 fund series, 39,065 ticker aliases; a rerun changes nothing.
- **Not covered:** OpenFIGI enrichment (FIGI is looked up per held security, not for the whole
  universe, because the free tier is 25 requests per minute).
