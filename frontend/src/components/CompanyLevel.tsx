import type { ExposureBar, Holding } from "../api/types";
import { companySources, swapSource } from "../lib/drill";
import { money, num, percent } from "../lib/format";
import { StackedBar, Swatch, type BarPart } from "./StackedBar";

interface Props {
  bar: ExposureBar;
  holdings: Holding[];
  hues: Map<number, string>;
  total: number;
  onOpenHolding: (id: number) => void;
  onOpenEvidence: (edgeId: number) => void;
}

/**
 * One company, opened: how much of your portfolio rides on it and through which holdings. Stock
 * you hold (directly or inside funds) is one bar; swap exposure continues it in its own colour,
 * because it is leverage rather than money you hold.
 */
export function CompanyLevel({ bar, holdings, hues, total, onOpenHolding, onOpenEvidence }: Props) {
  const funded = num(bar.funded_share);
  const swap = num(bar.swap_share);
  const scale = Math.max(1, funded + swap) * 1.02;
  const sources = companySources(bar.name, holdings);
  const viaSwap = swapSource(bar, holdings);

  const parts: BarPart[] = [];
  let x = 0;
  for (const s of sources) {
    const w = s.value / (total || 1);
    const hue = hues.get(s.holdingId) ?? "var(--node-muted)";
    parts.push({
      key: `src-${s.holdingId}`,
      label: s.via === "direct" ? `${s.holding} (direct)` : `via ${s.holding}`,
      x,
      w,
      fill: hue,
      provisional: s.provisional,
      onClick: s.edgeId != null ? () => onOpenEvidence(s.edgeId as number) : undefined,
      ariaLabel: `${money(s.value)} ${s.via === "direct" ? "held directly as" : "through"} ${s.holding}`,
      tip: (
        <>
          <b>{money(s.value)}</b>
          <div>{s.via === "direct" ? `Held directly as ${s.holding}` : `Inside ${s.holding}`}</div>
          <div className="muted">{percent(w)} of your portfolio</div>
          {s.edgeId != null && <div className="muted">Click for the filing text</div>}
        </>
      ),
    });
    x += w;
  }
  if (swap > 0) {
    parts.push({
      key: "swap",
      label: viaSwap ? `swaps in ${viaSwap.holding}` : "swaps",
      x,
      w: swap,
      fill: "var(--series-7)",
      onClick: bar.swap_edge_id != null ? () => onOpenEvidence(bar.swap_edge_id as number) : undefined,
      ariaLabel: `${money(bar.swap)} of swap exposure${viaSwap ? ` through ${viaSwap.holding}` : ""}`,
      tip: (
        <>
          <b>{money(bar.swap)}</b>
          <div>Swap exposure{viaSwap ? ` through ${viaSwap.holding}` : ""}</div>
          <div className="muted">{percent(swap)} of your portfolio. Leverage, not money you hold.</div>
          {bar.swap_edge_id != null && <div className="muted">Click for the filing text</div>}
        </>
      ),
    });
  }

  return (
    <>
      <div className="level-head">
        <div>
          <h2 className="level-title">{bar.name}</h2>
          <p className="muted">
            {swap > 0
              ? "Your exposure is stock you hold plus swap exposure from a leveraged fund. The swaps are measured by their filed notional over the fund's assets at its report date; leveraged funds rebalance daily, so treat it as approximate."
              : "Your exposure is the stock you hold in it, directly and inside your funds."}
          </p>
        </div>
        <div className="level-figure">
          <b>{percent(bar.total_share)}</b>
          <span className="muted">of your portfolio</span>
        </div>
      </div>

      <ul className="legend" aria-label="Key">
        {sources.map((s) => (
          <li key={s.holdingId}>
            <Swatch fill={hues.get(s.holdingId) ?? "var(--node-muted)"} />
            {s.via === "direct" ? `${s.holding}, held directly` : `Stock inside ${s.holding}`}
          </li>
        ))}
        {swap > 0 && (
          <li>
            <Swatch fill="var(--series-7)" />
            Swap exposure
          </li>
        )}
      </ul>
      <StackedBar
        parts={parts}
        scale={scale}
        markers={funded + swap > 1.005 ? [{ at: 1, label: "100% of your portfolio" }] : []}
        ariaLabel={`Your exposure to ${bar.name}, by where it comes from`}
      />

      <div className="groups">
        <section className="group">
          <h3>
            Stock you hold <span className="muted">{percent(bar.funded_share)} · {money(bar.funded)}</span>
          </h3>
          {sources.length === 0 && <p className="muted">None of your holdings lists this company by name.</p>}
          <ol className="ranked">
            {sources.map((s) => (
              <li key={s.holdingId}>
                <span className="row">
                  <span className="r-name">
                    <Swatch fill={hues.get(s.holdingId) ?? "var(--node-muted)"} className={s.provisional ? "provisional" : ""} />
                    <span className="r-label">
                      <button type="button" className="link" onClick={() => onOpenHolding(s.holdingId)}>
                        {s.holding}
                      </button>
                      <span className="r-sub">{s.via === "direct" ? "held directly" : "inside the fund"}</span>
                      {s.provisional && <span className="chip">provisional</span>}
                    </span>
                  </span>
                  <span className="r-track" aria-hidden="true">
                    <span className="r-fill" style={{ width: `${Math.min(100, (s.value / (num(bar.funded) + num(bar.swap) || 1)) * 100)}%`, background: hues.get(s.holdingId) ?? "var(--node-muted)" }} />
                  </span>
                  <span className="r-value">{money(s.value)}</span>
                  <span className="r-share">{percent(s.value / (total || 1))}</span>
                  {s.edgeId != null ? (
                    <button type="button" className="link r-go" onClick={() => onOpenEvidence(s.edgeId as number)} aria-label={`Filing text for ${bar.name} in ${s.holding}`}>
                      ›
                    </button>
                  ) : (
                    <span className="r-go" aria-hidden="true" />
                  )}
                </span>
              </li>
            ))}
          </ol>
        </section>
        {swap > 0 && (
          <section className="group">
            <h3>
              Swap exposure <span className="muted">{percent(bar.swap_share)} · {money(bar.swap)}</span>
            </h3>
            <ol className="ranked">
              <li>
                <span className="row">
                  <span className="r-name">
                    <Swatch fill="var(--series-7)" />
                    <span className="r-label">
                      {viaSwap ? (
                        <button type="button" className="link" onClick={() => onOpenHolding(viaSwap.holding_id)}>
                          {viaSwap.holding}
                        </button>
                      ) : (
                        "Swaps"
                      )}
                      <span className="r-sub">total return swaps, by notional</span>
                    </span>
                  </span>
                  <span className="r-track" aria-hidden="true">
                    <span className="r-fill" style={{ width: `${Math.min(100, (num(bar.swap) / (num(bar.funded) + num(bar.swap) || 1)) * 100)}%`, background: "var(--series-7)" }} />
                  </span>
                  <span className="r-value">{money(bar.swap)}</span>
                  <span className="r-share">{percent(bar.swap_share)}</span>
                  {bar.swap_edge_id != null ? (
                    <button type="button" className="link r-go" onClick={() => onOpenEvidence(bar.swap_edge_id as number)} aria-label="Filing text for the swaps">
                      ›
                    </button>
                  ) : (
                    <span className="r-go" aria-hidden="true" />
                  )}
                </span>
              </li>
            </ol>
          </section>
        )}
      </div>
    </>
  );
}
