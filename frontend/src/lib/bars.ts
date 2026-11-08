import type { Holding, Segment } from "../api/types";
import { num } from "./format";

export interface Rect {
  segment: Segment;
  /** Distance from the left edge of the bar area, in the same unit as `width`. */
  x: number;
  width: number;
}

export interface HoldingLayout {
  /** What the holding is made of: stock and collateral, drawn left to right. */
  positives: Rect[];
  /** What the fund owes, drawn stepping back from the end of the positives toward the total. */
  negatives: Rect[];
  /** Where the positives end (the gross), and where the negatives bring it back to (the net). */
  gross: number;
  net: number;
}

/**
 * Lay a holding's segments out as a bridge. Positive segments run left to right to the gross;
 * negative ones (swaps owed) then walk back from the gross toward the holding's own value, so the
 * stack lands on 100% of what you hold and the length of the walk back is what the fund owes.
 * `unit` is pixels per 100% of the holding's value.
 */
export function layoutHolding(segments: Segment[], unit: number): HoldingLayout {
  const positives: Rect[] = [];
  const negatives: Rect[] = [];
  let x = 0;
  for (const segment of segments) {
    const width = num(segment.share) * unit;
    if (width > 0) {
      positives.push({ segment, x, width });
      x += width;
    }
  }
  const gross = x;
  for (const segment of segments) {
    const width = num(segment.share) * unit;
    if (width < 0) {
      x += width; // width is negative: step back
      negatives.push({ segment, x, width: -width });
    }
  }
  return { positives, negatives, gross, net: x };
}

/** The longest gross among the holdings (at least 100%), as a multiple of each holding's value. */
export function maxGross(holdings: Holding[]): number {
  let longest = 1;
  for (const h of holdings) {
    const gross = h.segments.reduce((sum, s) => sum + Math.max(0, num(s.share)), 0);
    longest = Math.max(longest, gross);
  }
  return longest;
}
