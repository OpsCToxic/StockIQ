import type { RankedRow } from "../lib/drill";
import { money, percent } from "../lib/format";
import { Swatch } from "./StackedBar";

interface Props {
  rows: RankedRow[];
  /** The value that spans the full track width (the largest row, or the parent's value). */
  scale: number;
  fill: string;
  /** What `share` is a share of, for the column heading on the right. */
  shareOf: string;
  onOpenEvidence: (edgeId: number) => void;
}

/**
 * A ranked list of parts as thin bars: one hue, length is value. Rows that rest on a filed line
 * are buttons that open the filing text. Values are printed, so nothing depends on hover.
 */
export function RankedList({ rows, scale, fill, shareOf, onOpenEvidence }: Props) {
  if (rows.length === 0) return null;
  return (
    <ol className="ranked" aria-label={`Parts, as a share of ${shareOf}`}>
      {rows.map((r) => {
        const width = `${Math.min(100, (r.value / (scale || 1)) * 100)}%`;
        const body = (
          <>
            <span className="r-name">
              <Swatch fill={fill} className={r.provisional ? "provisional" : ""} />
              <span className="r-label">
                {r.label}
                {r.sublabel && <span className="r-sub">{r.sublabel}</span>}
                {r.provisional && <span className="chip">provisional</span>}
              </span>
            </span>
            <span className="r-track" aria-hidden="true">
              <span className={`r-fill ${fill === "hatch" ? "hatched" : ""}`} style={{ width, background: fill === "hatch" ? undefined : fill }} />
            </span>
            <span className="r-value">{money(r.value)}</span>
            <span className="r-share">{percent(r.share)}</span>
          </>
        );
        return (
          <li key={r.key} title={r.note}>
            {r.edgeId != null ? (
              <button type="button" className="row" onClick={() => onOpenEvidence(r.edgeId as number)} aria-label={`${r.label}, ${money(r.value)}, open the filing text`}>
                {body}
                <span className="r-go" aria-hidden="true">
                  ›
                </span>
              </button>
            ) : (
              <span className="row">
                {body}
                <span className="r-go" aria-hidden="true" />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
