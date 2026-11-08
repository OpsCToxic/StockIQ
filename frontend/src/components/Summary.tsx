import type { ExposureResponse, Flag } from "../api/types";
import { dateLabel, money, num, percent } from "../lib/format";

const BASIS_WORDS: Record<string, string> = {
  funded: "of your money",
  economic: "of your money, counting swaps",
};

function flagSentence(f: Flag): string {
  if (f.kind === "coverage") {
    return `${percent(f.share)} of your portfolio is stock in funds not yet tied to a company`;
  }
  return `${f.name} is ${percent(f.share)} ${BASIS_WORDS[f.basis] ?? ""} (${f.kind})`;
}

/** The hero figure and the handful of numbers that frame the drill-down. */
export function Summary({ data }: { data: ExposureResponse }) {
  const economic = data.herfindahl.find((h) => h.basis === "economic");
  const funded = data.herfindahl.find((h) => h.basis === "funded");
  const largest = data.exposure[0];
  const snapshots = Object.values(data.snapshot_as_of).map(dateLabel);

  return (
    <section className="summary">
      <div className="hero">
        <p className="hero-value">{money(data.total_value)}</p>
        <p className="muted">
          Portfolio value from your broker{snapshots.length ? `, snapshot ${snapshots.join(", ")}` : ""}.{" "}
          {data.reconciles ? "The parts add up to this total." : "Warning: the parts do not add up to this total."}
        </p>
      </div>
      <dl className="kpis">
        <div className="kpi">
          <dt>Traced to companies</dt>
          <dd>{percent(data.covered_fraction, 0)}</dd>
          <p className="muted">the rest is cash, collateral and derivatives</p>
        </div>
        {largest && (
          <div className="kpi">
            <dt>Largest exposure</dt>
            <dd>{percent(largest.total_share, 0)}</dd>
            <p className="muted">
              {largest.name}
              {num(largest.swap_share) > 0 ? ", counting swaps" : ""}
            </p>
          </div>
        )}
        {economic && (
          <div className="kpi">
            <dt>Effective companies</dt>
            <dd>{num(economic.effective_n).toFixed(1)}</dd>
            <p className="muted">
              counting swaps{funded ? `; ${num(funded.effective_n).toFixed(1)} by money held` : ""} (Herfindahl {num(economic.hhi).toFixed(2)})
            </p>
          </div>
        )}
      </dl>
      {data.flags.length > 0 && (
        <ul className="flags" aria-label="What stands out">
          {data.flags.map((f) => (
            <li key={`${f.kind}-${f.basis}-${f.name}`}>
              <span className="flag-mark" aria-hidden="true">
                ⚑
              </span>
              {flagSentence(f)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
