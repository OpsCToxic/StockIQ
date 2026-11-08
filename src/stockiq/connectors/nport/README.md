# nport

SEC Form N-PORT fund holdings, the source for ETF look-through. Quarterly public data, about a
60-day lag, so holdings are always somewhat stale: show the `as_of` date wherever they are used.

- **Discovery:** EDGAR's per-series Atom feed,
  `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=<series id>&type=NPORT-P&output=atom`.
  A series id (`S000002839`) works as the CIK there. Each filing's `primary_doc.xml` is then fetched.
- **Auth and limits:** none, but `SEC_USER_AGENT` (with a contact email) is required and the client
  stays at 5 req/s (SEC allows 10). Public data.
- **Run:** `python -m stockiq.connectors.nport` covers every fund you hold; or pass tickers
  (`... nport VOO`). Needs the `sec_tickers` seed first. Takes the newest unseen filing per series.
- **Point-in-time:** `fund_holding.as_of` is the report date; `known_at` (and `edge.known_at`) is the
  public filing date, treated as public from the next midnight ET. Edges are valid from the report
  date until the fund's next report starts.
- **Resolution:** exact CUSIP/ISIN/LEI first (confidence 1.0), then a unique normalised company name
  (0.95). An ambiguous name is left unresolved, never guessed. A confident name match records the
  CUSIP/ISIN as an alias, so the next filing matches exactly. This is the minimal Phase 1 resolver;
  the full resolver and review queue are Phase 2.
- **Edges:** CONTAINS, fund to company, only for long common/preferred equity lines. Share classes
  of one company (GOOG/GOOGL) are one edge with the summed weight (`pctVal / 100`, a fraction of net
  assets) and one evidence row per class. Each evidence row quotes the filed `<invstOrSec>` XML
  verbatim, with the filing URL (invariant 1).
- **Everything is kept:** every reported line goes in `fund_holding`, resolved or not, so unresolved
  weight stays visible. First live run: VOO 475 of 520 lines resolved, 96.5% of net assets.
- **Fund names:** the series name replaces the ticker placeholder from `sec_tickers`.
- **Known gaps (do not hide these in the exposure numbers):**
  - **Only ticker-referenced swaps become exposure.** A leveraged fund like TSLL holds Tesla
    mostly through total-return swaps. Each swap with a ticker reference becomes a SYNTHETIC edge
    (signed notional over net assets, evidence quoting the filed swap XML): TSLL's seven swaps are
    1.84x net assets, plus 0.16x direct stock, about 2x Tesla. Direction comes from which leg
    pays the interest rate. Futures, options, forwards and swaps on an index or basket are stored
    in `fund_holding` but not turned into exposure. Debt and cash are not rolled up either.
  - Weights sum to about 100% of net assets, not exactly (VOO 100.09%).
  - Names the SEC entity file lists differently (a holding company rename, "Cos" vs "Companies")
    stay unresolved until the Phase 2 resolver.
  - Only the newest filing is fetched by default; backfill history with `max_filings`.
- **Fixtures:** `tests/fixtures/nport/` has a real VOO filing trimmed to 10 holdings, the real
  Atom feed, and TSLL's full real filing (13 lines, 7 swaps). SEC data is public.
