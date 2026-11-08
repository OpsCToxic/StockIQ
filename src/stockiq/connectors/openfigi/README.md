# openfigi

Looks up FIGIs for a given list of tickers (held securities, ETF constituents) and stores them as
`figi` aliases. Not run for the whole universe: the free tier is too slow for 20,000 symbols.

- **Endpoint:** `POST https://api.openfigi.com/v3/mapping`, jobs `{"idType":"TICKER","idValue":...,"exchCode":"US"}`.
- **Auth:** optional. `OPENFIGI_API_KEY` in `.env` is sent as `X-OPENFIGI-APIKEY`.
- **Rate limits (docs, 2026-11-08):** without a key 25 requests/min and 10 jobs/request; with a key
  250 requests/min and 100 jobs/request. The client picks the limits from whether a key is set.
- **Terms:** FIGI identifiers are dedicated to the public domain (Bloomberg terms, 2018). No
  storage or caching limit found. The terms don't speak to the other returned fields (name, ticker).
- **Matching:** a ticker links to an entity through its open `ticker` alias. One composite FIGI on
  the US composite listing is a match. Zero is `not_found`, more than one is `ambiguous`; neither
  is guessed. Unlinked tickers are listed in `connector.unlinked` and printed by the CLI.
- **Share classes:** `BRK-B` is queried as `BRK/B`. One company can hold several FIGIs (one per
  class), so they live in `entity_alias` (kind `figi`), not in the single `entity.figi` column.
- **Raw payload:** `{"tickers", "request", "response"}`. `response` is OpenFIGI's reply verbatim.
- **Run:** `python -m stockiq.connectors.openfigi AAPL GOOGL VOO` (needs Postgres, MinIO, and the
  entity seed first).
- **Fixture:** a real 2026-11-08 response for AAPL, GOOGL, VOO, BRK-B and one unknown ticker.
- **Known quirk:** the docs show a no-match as both `warning` and `error`; both parse as a miss.
