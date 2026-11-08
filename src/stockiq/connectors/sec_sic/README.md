# sec_sic

Sector classification from SEC submissions: each company's SIC code and description, stored as an
`IN_SECTOR` edge to a sector entity named like `SIC 3571 Electronic Computers`.

- **Endpoint:** `https://data.sec.gov/submissions/CIK##########.json` (about 160 KB each, stored raw
  and gzipped). Public; needs `SEC_USER_AGENT`; 5 req/s.
- **Run:** `python -m stockiq.connectors.sec_sic` classifies every company in your look-through
  (direct holdings and anything a fund contains or references through swaps). Pass CIKs to
  override. First run: 473 companies, none skipped, about 2 minutes.
- **Evidence:** each edge cites the stored document and the JSON exactly as served,
  `"sic":"3571","sicDescription":"Electronic Computers"` (invariant 1).
- **Point-in-time:** SEC serves only the current SIC, so an edge's `valid_from` equals its
  `known_at`, the fetch time: "known from", not "true since". It is known from the fetch time and
  never backdated: an `as_of` before the first fetch shows the company as Unclassified. A changed
  SIC closes the old edge and opens a new one.
- **Why SIC:** it is the only free classification SEC publishes. GICS is licensed. SIC is coarser
  and older (Tesla is "Motor Vehicles", NVIDIA "Semiconductors", Alphabet "Computer Programming").
  The report shows the 4-digit industry and the ten SIC divisions (`graph/sic.py`); Manufacturing
  is one division containing hardware, drugs and cars, so read the industry lines too.
- **Funded value only:** the sector view uses what you hold through each fund, not swap exposure.
  A leveraged fund's swap-backed exposure shows only in the economic-exposure section.
- **Gaps:** shells and funds with no SIC are skipped and listed by the CLI, not guessed.
