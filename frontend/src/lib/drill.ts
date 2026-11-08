import type { ExposureBar, Holding, Segment } from "../api/types";
import { num } from "./format";

/** The kinds of part a holding is made of, in the order the drill-down groups them. */
export type Kind = Segment["kind"];

export interface KindTotals {
  stock: number;
  cash: number;
  unmatched: number;
  /** What the fund owes on its swaps, as a positive magnitude. */
  owed: number;
  /** Other, net: positive when it adds to the holding, negative when it takes away. */
  other: number;
}

/** Dollar totals of each kind of part inside a holding. */
export function kindTotals(holding: Holding): KindTotals {
  const t: KindTotals = { stock: 0, cash: 0, unmatched: 0, owed: 0, other: 0 };
  for (const s of holding.segments) {
    const v = num(s.value);
    switch (s.kind) {
      case "stock":
        t.stock += v;
        break;
      case "cash":
        t.cash += v;
        break;
      case "unmatched":
        t.unmatched += v;
        break;
      case "swap_owed":
        t.owed += -v;
        break;
      default:
        t.other += v;
    }
  }
  return t;
}

/** A holding is a plain stock position when its only part is one company at 100%. */
export function isDirectStock(holding: Holding): boolean {
  return holding.segments.length === 1 && holding.segments[0]!.kind === "stock";
}

/** The server folds the tail of a fund's companies into one "Other companies (N)" segment. */
export function isOtherCompanies(segment: Segment): boolean {
  return segment.kind === "stock" && /^Other companies \(\d+\)$/.test(segment.label);
}

/** Companies drawn as their own segment in a holding's bar; the rest fold into one segment. */
export const CHART_COMPANIES = 12;

/**
 * The segments to draw for a holding: the largest companies each get a segment, the tail becomes
 * one "N more companies" segment (absorbing the server's own fold), and the non-stock parts keep
 * their order. Every company is still listed by name below the chart.
 */
export function foldSegments(segments: Segment[], shown = CHART_COMPANIES): Segment[] {
  const named = segments
    .filter((s) => s.kind === "stock" && !isOtherCompanies(s))
    .sort((a, b) => num(b.value) - num(a.value));
  const serverOther = segments.find(isOtherCompanies);
  const rest = named.slice(shown);
  if (rest.length === 0) return segments;
  const serverCount = serverOther ? Number(/\((\d+)\)/.exec(serverOther.label)?.[1] ?? 0) : 0;
  const value = rest.reduce((sum, s) => sum + num(s.value), 0) + (serverOther ? num(serverOther.value) : 0);
  const share = rest.reduce((sum, s) => sum + num(s.share), 0) + (serverOther ? num(serverOther.share) : 0);
  const fold: Segment = {
    kind: "stock",
    label: `${rest.length + serverCount} more companies`,
    value: String(value),
    share: String(share),
    provisional: false,
    note: "Every company is listed by name below",
  };
  return [...named.slice(0, shown), fold, ...segments.filter((s) => s.kind !== "stock")];
}

/** Holdings take the categorical hues in a fixed order and never cycle: beyond eight, grey. */
export function holdingHue(index: number): string {
  return index < 8 ? `var(--series-${index + 1})` : "var(--node-muted)";
}

export interface CompanySource {
  holdingId: number;
  holding: string;
  /** "direct" for stock you hold yourself, "fund" for stock inside a fund you hold. */
  via: "direct" | "fund";
  value: number;
  edgeId: number | null;
  provisional: boolean;
}

/**
 * Where your stock in a company comes from: each holding that carries a stock segment with the
 * company's name. Direct positions first, then funds by value.
 */
export function companySources(name: string, holdings: Holding[]): CompanySource[] {
  const out: CompanySource[] = [];
  for (const h of holdings) {
    const direct = isDirectStock(h);
    for (const s of h.segments) {
      if (s.kind !== "stock" || s.label !== name) continue;
      out.push({
        holdingId: h.holding_id,
        holding: h.holding,
        via: direct ? "direct" : "fund",
        value: num(s.value),
        edgeId: s.edge_id ?? null,
        provisional: s.provisional,
      });
    }
  }
  return out.sort((a, b) => (a.via === b.via ? b.value - a.value : a.via === "direct" ? -1 : 1));
}

/** The holding whose swaps give you exposure to a company: the one with a swap segment that cites the same edge. */
export function swapSource(bar: ExposureBar, holdings: Holding[]): Holding | undefined {
  if (bar.swap_edge_id == null) return undefined;
  return holdings.find((h) => h.segments.some((s) => s.kind === "swap_owed" && s.edge_id === bar.swap_edge_id));
}

/**
 * One row of a ranked list inside a drill-down level: its width is `value / scale`, and it opens
 * the filing text when it has an edge.
 */
export interface RankedRow {
  key: string;
  label: string;
  sublabel?: string;
  value: number;
  /** Share of the parent (the holding, or the portfolio), for the printed percentage. */
  share: number;
  edgeId: number | null;
  provisional: boolean;
  note?: string;
}

export function rowsFor(segments: Segment[], kind: Kind): RankedRow[] {
  return segments
    .filter((s) => s.kind === kind)
    .map((s, i) => ({
      key: `${kind}-${i}-${s.label}`,
      label: s.label,
      value: Math.abs(num(s.value)),
      share: Math.abs(num(s.share)),
      edgeId: s.edge_id ?? null,
      provisional: s.provisional,
      note: s.note ?? undefined,
    }))
    .sort((a, b) => b.value - a.value);
}

/** Company rows: named companies ranked by value, with the server's "Other companies" fold last. */
export function companyRows(segments: Segment[]): { named: RankedRow[]; other: RankedRow | null } {
  const named = rowsFor(
    segments.filter((s) => !isOtherCompanies(s)),
    "stock",
  );
  const otherSeg = segments.find(isOtherCompanies);
  const other = otherSeg ? rowsFor([otherSeg], "stock")[0]! : null;
  return { named, other };
}
