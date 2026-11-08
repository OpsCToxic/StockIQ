import type { ExposureResponse, Holding } from "../api/types";
import { isDirectStock, kindTotals } from "../lib/drill";
import { dateLabel, money, num, percent } from "../lib/format";
import { StackedBar, Swatch, type BarPart } from "./StackedBar";

export type Lens = "holdings" | "companies";

interface Props {
  data: ExposureResponse;
  lens: Lens;
  setLens: (lens: Lens) => void;
  hues: Map<number, string>;
  onOpenHolding: (id: number) => void;
  onOpenCompany: (id: number) => void;
}

/**
 * The top of the drill-down. Two lenses on the same money: what you own (one segment per
 * holding, click to open it) and what you ride on (your exposure by company, funded stock plus
 * swaps, which can pass 100% because swaps are leverage).
 */
export function PortfolioLevel({ data, lens, setLens, hues, onOpenHolding, onOpenCompany }: Props) {
  return (
    <>
      <div className="lens" role="tablist" aria-label="Lens">
        <button type="button" role="tab" aria-selected={lens === "holdings"} onClick={() => setLens("holdings")}>
          Portfolio
        </button>
        <button type="button" role="tab" aria-selected={lens === "companies"} onClick={() => setLens("companies")}>
          Exposure
        </button>
      </div>
      {lens === "holdings" ? (
        <HoldingsLens data={data} hues={hues} onOpenHolding={onOpenHolding} />
      ) : (
        <CompaniesLens data={data} onOpenCompany={onOpenCompany} />
      )}
    </>
  );
}

function HoldingsLens({ data, hues, onOpenHolding }: Pick<Props, "data" | "hues" | "onOpenHolding">) {
  const total = num(data.total_value) || 1;
  const cash = num(data.cash);
  let x = 0;
  const parts: BarPart[] = data.holdings.map((h) => {
    const w = num(h.value) / total;
    const part: BarPart = {
      key: String(h.holding_id),
      label: h.holding,
      x,
      w,
      fill: hues.get(h.holding_id) ?? "var(--node-muted)",
      onClick: () => onOpenHolding(h.holding_id),
      ariaLabel: `${h.holding}, ${money(h.value)}, ${percent(h.share)} of your portfolio. Open it`,
      tip: (
        <>
          <b>{money(h.value)}</b>
          <div>
            {h.holding} · {h.name}
          </div>
          <div className="muted">{percent(h.share)} of your portfolio · click to open</div>
        </>
      ),
    };
    x += w;
    return part;
  });
  if (cash > 0) {
    parts.push({
      key: "cash",
      label: "Cash",
      x,
      w: cash / total,
      fill: "hatch",
      ariaLabel: `Cash, ${money(cash)}`,
      tip: (
        <>
          <b>{money(cash)}</b>
          <div>Cash at your broker</div>
        </>
      ),
    });
  }

  return (
    <>
      <p className="lead">
        Your {money(data.total_value)}, holding by holding. Pick one to see what it is made of.
      </p>
      <StackedBar parts={parts} scale={1} ariaLabel="Your portfolio split by holding" />
      <ol className="holdings">
        {data.holdings.map((h) => (
          <li key={h.holding_id}>
            <HoldingCard holding={h} hue={hues.get(h.holding_id) ?? "var(--node-muted)"} onOpen={() => onOpenHolding(h.holding_id)} />
          </li>
        ))}
        {cash > 0 && (
          <li>
            <div className="hcard static">
              <div className="h-head">
                <Swatch fill="hatch" />
                <span className="h-ticker">Cash</span>
                <span className="h-name">At your broker</span>
              </div>
              <div className="h-figures">
                <b>{money(cash)}</b>
                <span className="muted">{percent(cash / total)}</span>
              </div>
            </div>
          </li>
        )}
      </ol>
    </>
  );
}

/** Whole percent for a card footer; a sliver that would round to 0% says "<1%" instead. */
function roughPercent(fraction: number): string {
  return fraction > 0 && fraction < 0.005 ? "<1%" : percent(fraction, 0);
}

/** A holding at a glance: value, share, and a strip of what it is made of, by kind. */
function HoldingCard({ holding, hue, onOpen }: { holding: Holding; hue: string; onOpen: () => void }) {
  const t = kindTotals(holding);
  const gross = t.stock + t.cash + t.unmatched + Math.max(0, t.other) || 1;
  const strip: { key: string; label: string; value: number; fill: string }[] = [
    { key: "stock", label: "Company stock", value: t.stock, fill: hue },
    { key: "cash", label: "Cash and collateral", value: t.cash, fill: "hatch" },
    { key: "unmatched", label: "Equity not matched to a company", value: t.unmatched, fill: "var(--series-4)" },
    { key: "other", label: "Other, net", value: Math.max(0, t.other), fill: "var(--node-muted)" },
  ].filter((s) => s.value > 0);
  const value = num(holding.value) || 1;
  const direct = isDirectStock(holding);

  return (
    <button type="button" className="hcard" onClick={onOpen} aria-label={`Open ${holding.holding}`}>
      <div className="h-head">
        <Swatch fill={hue} />
        <span className="h-ticker">{holding.holding}</span>
        <span className="h-name">{holding.name}</span>
        <span className="h-go" aria-hidden="true">
          ›
        </span>
      </div>
      <div className="h-figures">
        <b>{money(holding.value)}</b>
        <span className="muted">{percent(holding.share)} of your portfolio</span>
      </div>
      <div className="strip" aria-hidden="true">
        {strip.map((s) => (
          <span key={s.key} className={`strip-seg ${s.fill === "hatch" ? "hatched" : ""}`} style={{ flexGrow: s.value / gross, background: s.fill === "hatch" ? undefined : s.fill }} title={`${s.label}: ${money(s.value)}`} />
        ))}
      </div>
      <div className="h-foot muted">
        {direct ? (
          <span>Direct stock position</span>
        ) : (
          <>
            <span>{roughPercent(t.stock / value)} stock</span>
            {t.cash > 0 && <span>{roughPercent(t.cash / value)} cash and collateral</span>}
            {t.owed > 0 && <span className="owed-tag">owes {roughPercent(t.owed / value)} on swaps</span>}
            {t.unmatched > 0 && <span>{roughPercent(t.unmatched / value)} unmatched</span>}
          </>
        )}
        {holding.report_as_of && <span className="h-asof">filed {dateLabel(holding.report_as_of)}</span>}
      </div>
    </button>
  );
}

function CompaniesLens({ data, onOpenCompany }: Pick<Props, "data" | "onOpenCompany">) {
  const bars = data.exposure;
  const longest = Math.max(1, ...bars.map((b) => num(b.total_share))) * 1.02;
  const pct = (share: number) => `${(share / longest) * 100}%`;
  const anySwap = bars.some((b) => num(b.swap_share) > 0);

  return (
    <>
      <p className="lead">
        Your exposure to each company: stock you hold directly and through funds
        {anySwap ? ", plus swap exposure. A bar can pass your whole portfolio because swaps are leverage, not money you hold." : "."}{" "}
        Pick one to see where it comes from.
      </p>
      {anySwap && (
        <ul className="legend" aria-label="Key">
          <li>
            <Swatch fill="var(--accent)" />
            Stock you hold
          </li>
          <li>
            <Swatch fill="var(--series-7)" />
            Swap exposure
          </li>
        </ul>
      )}
      <ol className="ranked companies">
        {bars.map((b) => {
          const funded = num(b.funded_share);
          const swap = num(b.swap_share);
          return (
            <li key={b.company_id}>
              <button type="button" className="row" onClick={() => onOpenCompany(b.company_id)} aria-label={`${b.name}, ${percent(b.total_share)} of your portfolio. Open it`}>
                <span className="r-name">
                  <span className="r-label">{b.name}</span>
                </span>
                <span className="r-track tall" aria-hidden="true">
                  <span className="r-fill" style={{ width: pct(funded), background: "var(--accent)" }} />
                  {swap > 0 && <span className="r-fill" style={{ left: pct(funded), width: pct(swap), background: "var(--series-7)", position: "absolute" }} />}
                  {longest > 1.02 && <span className="r-line" style={{ left: pct(1) }} />}
                </span>
                <span className="r-value">{money(num(b.funded) + num(b.swap))}</span>
                <span className="r-share">{percent(b.total_share)}</span>
                <span className="r-go" aria-hidden="true">
                  ›
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {longest > 1.02 && <p className="muted">The vertical line marks 100% of your portfolio.</p>}
    </>
  );
}
