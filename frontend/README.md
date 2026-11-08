# StockIQ frontend

A separate app (ADR 0003): React, TypeScript, Vite; charts are plain SVG/HTML. The first page is
the Exposure X-ray: a hero figure and three KPI tiles, then one drill-down chart.
Portfolio level: "Portfolio" (one stacked bar of holdings, a card per holding) or "Exposure"
(exposure by company, stock plus swaps). Open a holding to see what it is made of
(stock, cash and collateral, swaps owed, ranked and grouped); open a company to see which holdings
it comes through. Any part that rests on a filed line opens the filing text in a drawer.
The caveats sit under "About these numbers".

## Run
```
make api        # FastAPI on 127.0.0.1:8000 (needs Postgres up and .env loaded)
make frontend   # Vite on 127.0.0.1:5173; it proxies /api to the backend
```
Both bind to localhost only. The API has no login: put it behind Tailscale or an auth proxy before
exposing it anywhere (docs/architecture.md, "Security").

## Typed API client
`src/api/schema.d.ts` is generated from the backend's OpenAPI spec, so the types cannot drift:
```
cd frontend && npm run gen:api
```
(it runs `scripts/export_openapi.py`, which needs the Python environment and `.env` loaded; the
spec and generated types are committed so the app builds without a running backend.)

## Checks
`make frontend-check` runs the typecheck, the unit tests (`vitest`) and a production build.

## Notes
- Money arrives as decimal strings; `src/lib/format.ts` is the one place they become numbers.
- Chart colours are the validated categorical palette (dataviz skill), one hue per holding by id,
  never cycled; beyond eight holdings the rest are grey. Colours live in `src/styles.css` as tokens
  for light and dark. "Not looked through" is hatched as well as grey, and every chart has a table.
- A holding's bar: stock and collateral run left to right; what a fund owes on its swaps steps
  back underneath and lands on the 100% line (what you hold), so a fund with swaps (for now, TSLL)
  visibly runs past 100%. The twelve largest companies get their own segment and the rest fold
  into one; the ranked list below names every company (`src/lib/drill.ts`, unit-tested).
- The app asks the API for `top=1000` companies per fund so the drill-down is complete; the
  `/portfolio/exposure` cap was raised to match.
- `STOCKIQ_API=http://127.0.0.1:8001 npm run dev` points the dev proxy at another backend.
