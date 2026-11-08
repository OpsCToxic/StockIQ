import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchExposure } from "./api/client";
import type { ExposureResponse } from "./api/types";
import { CompanyLevel } from "./components/CompanyLevel";
import { EvidenceDrawer } from "./components/EvidenceDrawer";
import { HoldingLevel } from "./components/HoldingLevel";
import { PortfolioLevel, type Lens } from "./components/PortfolioLevel";
import { Summary } from "./components/Summary";
import { holdingHue } from "./lib/drill";
import { num } from "./lib/format";

// Ask the API for every company inside each fund, so the drill-down can list them all.
const ALL_COMPANIES = 1000;

type Load =
  | { status: "loading"; previous?: ExposureResponse }
  | { status: "error"; message: string }
  | { status: "ok"; data: ExposureResponse };

/** Where the drill-down is: the whole portfolio, one holding, or one company. */
type View = { level: "portfolio" } | { level: "holding"; id: number } | { level: "company"; id: number };

export default function App() {
  const [asOfDate, setAsOfDate] = useState("");
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [view, setView] = useState<View>({ level: "portfolio" });
  const [lens, setLens] = useState<Lens>("holdings");
  const [edgeId, setEdgeId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoad((prev) => ({ status: "loading", previous: prev.status === "ok" ? prev.data : undefined }));
    setEdgeId(null);
    // A date means "as of the end of that day"; empty means now.
    fetchExposure(asOfDate ? `${asOfDate}T23:59:59Z` : undefined, ALL_COMPANIES)
      .then((data) => {
        if (!cancelled) setLoad({ status: "ok", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoad({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [asOfDate]);

  const closeEvidence = useCallback(() => setEdgeId(null), []);
  const data = load.status === "ok" ? load.data : load.status === "loading" ? load.previous : undefined;

  return (
    <main>
      <header className="topbar">
        <div>
          <h1>Exposure X-ray</h1>
          <p className="muted">What your money really rides on, including what is inside your funds.</p>
        </div>
        <label className="asof">
          <span>As of</span>
          <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} aria-describedby="asof-help" />
        </label>
      </header>
      <p id="asof-help" className="muted asof-help">
        Leave empty for now. A past date uses only what was publicly known by then.
      </p>

      {load.status === "error" && (
        <p className="error" role="alert">
          {load.message}
        </p>
      )}
      {load.status === "loading" && !data && <p className="muted">Loading…</p>}

      {data && (
        <div className={load.status === "loading" ? "page refetching" : "page"}>
          <Summary data={data} />
          <Drill data={data} view={view} setView={setView} lens={lens} setLens={setLens} onOpenEvidence={setEdgeId} />
          <details className="notes">
            <summary>About these numbers</summary>
            <ul>
              {data.caveats.map((c) => (
                <li key={c}>{c}</li>
              ))}
              <li>These describe what you hold at the dates shown. They are not predictions.</li>
            </ul>
          </details>
        </div>
      )}
      {edgeId != null && <EvidenceDrawer edgeId={edgeId} onClose={closeEvidence} />}
    </main>
  );
}

function Drill(props: {
  data: ExposureResponse;
  view: View;
  setView: (view: View) => void;
  lens: Lens;
  setLens: (lens: Lens) => void;
  onOpenEvidence: (edgeId: number) => void;
}) {
  const { data, view, setView, lens, setLens, onOpenEvidence } = props;
  const total = num(data.total_value);
  // Hues follow the holding, in value order, and never cycle.
  const hues = useMemo(() => new Map(data.holdings.map((h, i) => [h.holding_id, holdingHue(i)])), [data.holdings]);

  // A view can point at something a different as-of date no longer has; fall back to the top.
  const holding = view.level === "holding" ? data.holdings.find((h) => h.holding_id === view.id) : undefined;
  const bar = view.level === "company" ? data.exposure.find((b) => b.company_id === view.id) : undefined;
  const current = view.level === "portfolio" ? "portfolio" : holding ? "holding" : bar ? "company" : "portfolio";

  const openHolding = (id: number) => setView({ level: "holding", id });
  const openCompany = (id: number) => setView({ level: "company", id });

  return (
    <section className="card drill" aria-labelledby="drill-h">
      <nav className="crumbs" aria-label="Where you are">
        <ol>
          <li>
            {current === "portfolio" ? (
              <span aria-current="page" id="drill-h">
                Portfolio
              </span>
            ) : (
              <button type="button" className="link" onClick={() => setView({ level: "portfolio" })}>
                Portfolio
              </button>
            )}
          </li>
          {current === "holding" && holding && (
            <li aria-current="page" id="drill-h">
              {holding.holding}
            </li>
          )}
          {current === "company" && bar && (
            <li aria-current="page" id="drill-h">
              {bar.name}
            </li>
          )}
        </ol>
        {current !== "portfolio" && (
          <button type="button" className="back" onClick={() => setView({ level: "portfolio" })}>
            ‹ Back
          </button>
        )}
      </nav>
      <div className="level" key={`${current}-${view.level === "portfolio" ? lens : view.id}`}>
        {current === "portfolio" && (
          <PortfolioLevel data={data} lens={lens} setLens={setLens} hues={hues} onOpenHolding={openHolding} onOpenCompany={openCompany} />
        )}
        {current === "holding" && holding && (
          <HoldingLevel holding={holding} hue={hues.get(holding.holding_id) ?? "var(--node-muted)"} total={total} onOpenEvidence={onOpenEvidence} />
        )}
        {current === "company" && bar && (
          <CompanyLevel bar={bar} holdings={data.holdings} hues={hues} total={total} onOpenHolding={openHolding} onOpenEvidence={onOpenEvidence} />
        )}
      </div>
    </section>
  );
}
