import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/** One painted piece of a stacked bar. `x` and `w` are fractions of the bar's scale. */
export interface BarPart {
  key: string;
  label: string;
  x: number;
  w: number;
  /** A CSS colour, or "hatch" for the cash/collateral texture. */
  fill: string;
  /** The lower, thinner lane that walks back over what a fund owes. */
  lane?: "main" | "owed";
  /** A provisional company match: drawn lighter with a dashed edge. */
  provisional?: boolean;
  onClick?: () => void;
  tip: ReactNode;
  ariaLabel: string;
}

export interface BarMarker {
  at: number;
  label: string;
}

interface Props {
  parts: BarPart[];
  /** The fraction that spans the full width of the bar (1 = the parent's whole value). */
  scale: number;
  markers?: BarMarker[];
  ariaLabel: string;
  /** Thickness of the main lane, in px. */
  thickness?: number;
}

const GAP = 2; // the surface gap between touching segments
const OWED_LANE = 10;
const LANE_GAP = 6;
const MARKER_BAND = 18;
const CHAR = 6.6; // approximate width of a 12px character, for deciding if a label fits

interface Hover {
  part: BarPart;
  x: number;
  y: number;
}

/**
 * A horizontal stacked bar in plain SVG: thin marks, a 2px surface gap between segments, a
 * hairline marker for the 100% line, per-segment hover and focus tooltips, and inline labels only
 * where they fit. Segments with a click handler are buttons.
 */
export function StackedBar({ parts, scale, markers = [], ariaLabel, thickness = 24 }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [hover, setHover] = useState<Hover | null>(null);
  const patternId = useId().replace(/:/g, "");

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  const hasOwed = parts.some((p) => p.lane === "owed");
  const hasMarkers = markers.length > 0;
  const top = hasMarkers ? MARKER_BAND : 0;
  const height = top + thickness + (hasOwed ? LANE_GAP + OWED_LANE : 0);
  const px = (fraction: number) => (fraction / scale) * width;

  const show = (part: BarPart, clientX: number, clientY: number) => {
    const box = host.current?.getBoundingClientRect();
    if (box) setHover({ part, x: clientX - box.left, y: clientY - box.top });
  };

  return (
    <div className="stacked" ref={host}>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
        <defs>
          <pattern id={patternId} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--hatch-bg)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--hatch-fg)" strokeWidth="2" />
          </pattern>
        </defs>
        <rect x={0} y={top} width={width} height={thickness} rx={4} fill="var(--track)" />
        {parts.map((part) => {
          const owed = part.lane === "owed";
          const y = owed ? top + thickness + LANE_GAP : top;
          const h = owed ? OWED_LANE : thickness;
          const x = px(part.x);
          const w = Math.max(0, px(part.w) - GAP);
          if (w <= 0) return null;
          const clickable = part.onClick != null;
          const fill = part.fill === "hatch" ? `url(#${patternId})` : part.fill;
          const labelFits = !owed && part.label.length * CHAR + 16 <= w;
          return (
            <g
              key={part.key}
              className={clickable ? "seg clickable" : "seg"}
              transform={`translate(${x + GAP / 2},${y})`}
              tabIndex={clickable ? 0 : undefined}
              role={clickable ? "button" : undefined}
              aria-label={part.ariaLabel}
              onMouseMove={(e) => show(part, e.clientX, e.clientY)}
              onMouseLeave={() => setHover(null)}
              onFocus={(e) => {
                const r = e.currentTarget.getBoundingClientRect();
                show(part, r.left + r.width / 2, r.bottom);
              }}
              onBlur={() => setHover(null)}
              onClick={part.onClick}
              onKeyDown={(e) => {
                if (clickable && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  part.onClick?.();
                }
              }}
            >
              <rect
                width={w}
                height={h}
                rx={owed ? 3 : 4}
                fill={fill}
                fillOpacity={part.provisional ? 0.45 : 1}
                stroke={part.provisional ? "var(--text-secondary)" : "none"}
                strokeDasharray={part.provisional ? "3 2" : undefined}
              />
              {labelFits && (
                <text x={8} y={h / 2 + 4} className="seg-label" style={{ fill: part.fill === "hatch" ? "var(--text-primary)" : "var(--on-fill)" }}>
                  {part.label}
                </text>
              )}
            </g>
          );
        })}
        {markers.map((m) => (
          <g key={m.label} transform={`translate(${px(m.at)},0)`}>
            <line y1={top - 4} y2={height} stroke="var(--text-primary)" strokeWidth={1.5} />
            <text y={11} textAnchor={m.at / scale > 0.8 ? "end" : "start"} dx={m.at / scale > 0.8 ? -6 : 6} className="tick">
              {m.label}
            </text>
          </g>
        ))}
      </svg>
      {hover && (
        <div
          className="tip"
          role="tooltip"
          style={{ left: Math.min(hover.x + 14, Math.max(0, width - 280)), top: hover.y + 16 }}
        >
          {hover.part.tip}
        </div>
      )}
    </div>
  );
}

/** The one swatch key style used across the page, so every legend matches the marks. */
export function Swatch({ fill, className = "" }: { fill: string; className?: string }) {
  return (
    <span
      className={`swatch ${fill === "hatch" ? "hatched" : ""} ${className}`.trim()}
      style={fill === "hatch" ? undefined : { background: fill }}
      aria-hidden="true"
    />
  );
}
