import { useState } from "react";
import type { Holding, Segment } from "../api/types";
import { layoutHolding } from "../lib/bars";
import { companyRows, foldSegments, isDirectStock, kindTotals, rowsFor } from "../lib/drill";
import { dateLabel, money, num, percent } from "../lib/format";
import { RankedList } from "./RankedList";
import { StackedBar, Swatch, type BarPart } from "./StackedBar";

const SHOWN_COMPANIES = 10;

interface Props {
  holding: Holding;
  hue: string;
  /** The whole portfolio's value, to say what share of it a part is. */
  total: number;
  onOpenEvidence: (edgeId: number) => void;
}

function fillFor(segment: Segment, hue: string): string {
  switch (segment.kind) {
    case "stock":
      return hue;
    case "cash":
      return "hatch";
    case "swap_owed":
      return "var(--series-7)";
    case "unmatched":
      return "var(--series-4)";
    default:
      return "var(--node-muted)";
  }
}

/**
 * One holding, opened. The bar is what it is made of: stock and collateral run left to right;
 * what a fund owes on its swaps walks back underneath and lands on the line marking what you
 * hold. Below, every part ranked, grouped by kind, each opening the filing text behind it.
 */
export function HoldingLevel({ holding, hue, total, onOpenEvidence }: Props) {
  const [allCompanies, setAllCompanies] = useState(false);
  const value = num(holding.value) || 1;
  const t = kindTotals(holding);
  const layout = layoutHolding(foldSegments(holding.segments), 1);
  const scale = Math.max(1, layout.gross) * 1.02;
  const direct = isDirectStock(holding);

  const part = (segment: Segment, x: number, w: number, lane: "main" | "owed"): BarPart => ({
    key: `${lane}-${x}-${segment.label}`,
    label: segment.label,
    x,
    w,
    lane,
    fill: fillFor(segment, hue),
    provisional: segment.provisional,
    onClick: segment.edge_id != null ? () => onOpenEvidence(segment.edge_id as number) : undefined,
    ariaLabel: `${segment.label}, ${money(segment.value)}${segment.edge_id != null ? ", open the filing text" : ""}`,
    tip: (
      <>
        <b>{money(segment.value)}</b>
        <div>{segment.label}</div>
        <div className="muted">
          {percent(segment.share)} of {holding.holding} · {percent(num(segment.value) / (total || 1))} of your portfolio
        </div>
        {segment.note && <div className="muted">{segment.note}</div>}
        {segment.edge_id != null && <div className="muted">Click for the filing text</div>}
      </>
    ),
  });
  const parts = [
    ...layout.positives.map((r) => part(r.segment, r.x, r.width, "main")),
    ...layout.negatives.map((r) => part(r.segment, r.x, r.width, "owed")),
  ];

  const { named, other } = companyRows(holding.segments);
  const shownCompanies = allCompanies ? named : named.slice(0, SHOWN_COMPANIES);
  const cashRows = rowsFor(holding.segments, "cash");
  const owedRows = rowsFor(holding.segments, "swap_owed");
  const unmatchedRows = rowsFor(holding.segments, "unmatched");
  const otherRows = rowsFor(holding.segments, "other").map((r) => ({
    ...r,
    sublabel: t.other < 0 ? "a net liability, subtracted" : undefined,
  }));
  const widest = Math.max(...holding.segments.map((s) => Math.abs(num(s.value))), 1);

  return (
    <>
      <div className="level-head">
        <div>
          <h2 className="level-title">
            <Swatch fill={hue} className="big" />
            {holding.holding}
            <span className="level-sub">{holding.name}</span>
          </h2>
          <p className="muted">
            {direct
              ? "A stock you hold directly."
              : holding.report_as_of
                ? `A fund. Its holdings are from its filing as of ${dateLabel(holding.report_as_of)}; public fund filings are quarterly, about a 60-day lag.`
                : "A fund with no holdings filing known yet."}
          </p>
        </div>
        <div className="level-figure">
          <b>{money(holding.value)}</b>
          <span className="muted">{percent(holding.share)} of your portfolio</span>
        </div>
      </div>

      {!direct && (
        <ul className="legend" aria-label="Key">
          <li>
            <Swatch fill={hue} />
            Company stock
          </li>
          {t.cash > 0 && (
            <li>
              <Swatch fill="hatch" />
              Cash and collateral
            </li>
          )}
          {t.unmatched > 0 && (
            <li>
              <Swatch fill="var(--series-4)" />
              Equity not matched to a company
            </li>
          )}
          {t.owed > 0 && (
            <li>
              <Swatch fill="var(--series-7)" />
              Owed on swaps (steps back)
            </li>
          )}
          {t.other !== 0 && (
            <li>
              <Swatch fill="var(--node-muted)" />
              Other, net
            </li>
          )}
        </ul>
      )}
      <StackedBar
        parts={parts}
        scale={scale}
        markers={layout.gross > 1.005 ? [{ at: 1, label: "100% = what you hold" }] : []}
        ariaLabel={`What ${holding.holding} is made of`}
      />
      {t.owed > 0 && (
        <p className="muted">
          The fund holds {percent(layout.gross, 0)} of its value in stock and collateral and owes {percent(t.owed / value, 0)} back on its swaps, so it nets to what you hold.
        </p>
      )}

      {direct ? (
        <p className="lead">All of it is {holding.name} stock. Nothing to look through.</p>
      ) : (
        <div className="groups">
          {named.length > 0 && (
            <section className="group">
              <h3>
                Companies <span className="muted">{percent(t.stock / value)} · {money(t.stock)}</span>
              </h3>
              <RankedList rows={shownCompanies} scale={widest} fill={hue} shareOf={holding.holding} onOpenEvidence={onOpenEvidence} />
              {named.length > SHOWN_COMPANIES && (
                <button type="button" className="link" onClick={() => setAllCompanies((v) => !v)} aria-expanded={allCompanies}>
                  {allCompanies ? "Show fewer" : `Show all ${named.length} companies`}
                </button>
              )}
              {other && (
                <p className="muted">
                  {other.label}: {money(other.value)} more ({percent(other.share)}), not listed by name.
                </p>
              )}
            </section>
          )}
          {unmatchedRows.length > 0 && (
            <section className="group">
              <h3>
                Equity not matched to a company <span className="muted">{percent(t.unmatched / value)} · {money(t.unmatched)}</span>
              </h3>
              <RankedList rows={unmatchedRows} scale={widest} fill="var(--series-4)" shareOf={holding.holding} onOpenEvidence={onOpenEvidence} />
            </section>
          )}
          {cashRows.length > 0 && (
            <section className="group">
              <h3>
                Cash and collateral <span className="muted">{percent(t.cash / value)} · {money(t.cash)}</span>
              </h3>
              <RankedList rows={cashRows} scale={widest} fill="hatch" shareOf={holding.holding} onOpenEvidence={onOpenEvidence} />
            </section>
          )}
          {owedRows.length > 0 && (
            <section className="group">
              <h3>
                Owed on swaps <span className="muted">{percent(t.owed / value)} · {money(t.owed)}</span>
              </h3>
              <p className="muted">Swaps at fair value, where the fund owes the counterparty. The swaps are also what gives the fund its leveraged exposure.</p>
              <RankedList rows={owedRows} scale={widest} fill="var(--series-7)" shareOf={holding.holding} onOpenEvidence={onOpenEvidence} />
            </section>
          )}
          {otherRows.length > 0 && (
            <section className="group">
              <h3>
                Other, net <span className="muted">{money(t.other)}</span>
              </h3>
              <RankedList rows={otherRows} scale={widest} fill="var(--node-muted)" shareOf={holding.holding} onOpenEvidence={onOpenEvidence} />
            </section>
          )}
        </div>
      )}
    </>
  );
}
