import { describe, expect, it } from "vitest";
import type { Holding, Segment } from "../api/types";
import { layoutHolding, maxGross } from "./bars";

function seg(kind: Segment["kind"], label: string, share: number): Segment {
  return { kind, label, value: String(share * 1000), share: String(share), provisional: false } as Segment;
}

// TSLL: 15.7% stock + 142% money-market funds = 157.7% gross, then 57.7% owed brings it back to 100%
const tsll = [
  seg("stock", "Tesla", 0.157),
  seg("cash", "Dreyfus", 0.9),
  seg("cash", "Goldman", 0.52),
  seg("swap_owed", "Barclays", -0.4),
  seg("swap_owed", "BNP", -0.177),
];

describe("layoutHolding", () => {
  it("draws positives left to right and steps the negatives back to the holding's own value", () => {
    const layout = layoutHolding(tsll, 100);
    expect(layout.gross).toBeCloseTo(157.7);
    expect(layout.net).toBeCloseTo(100); // lands on 100% of what you hold
    expect(layout.positives.map((r) => r.segment.label)).toEqual(["Tesla", "Dreyfus", "Goldman"]);
  });

  it("starts each segment where the previous one ended, with nothing overlapping", () => {
    const { positives } = layoutHolding(tsll, 100);
    for (let i = 1; i < positives.length; i += 1) {
      const prev = positives[i - 1]!;
      expect(positives[i]!.x).toBeCloseTo(prev.x + prev.width);
    }
  });

  it("walks the negatives backward from the gross, so the first one sits at the far right", () => {
    const { negatives, gross } = layoutHolding(tsll, 100);
    expect(negatives[0]!.x + negatives[0]!.width).toBeCloseTo(gross);
    expect(negatives[1]!.x + negatives[1]!.width).toBeCloseTo(negatives[0]!.x);
    expect(negatives.every((r) => r.width > 0)).toBe(true);
  });

  it("a holding with nothing owed ends exactly at 100% and has no walk back", () => {
    const layout = layoutHolding([seg("stock", "A", 0.6), seg("cash", "MM", 0.4)], 200);
    expect(layout.gross).toBeCloseTo(200);
    expect(layout.net).toBeCloseTo(200);
    expect(layout.negatives).toEqual([]);
  });

  it("scales with the unit, not with anything else", () => {
    expect(layoutHolding(tsll, 200).gross).toBeCloseTo(2 * layoutHolding(tsll, 100).gross);
  });
});

describe("maxGross", () => {
  const holding = (segments: Segment[]): Holding => ({ segments }) as Holding;

  it("is the longest gross among the holdings", () => {
    expect(maxGross([holding(tsll), holding([seg("stock", "A", 1)])])).toBeCloseTo(1.577);
  });

  it("is at least 100%, even when every holding is smaller", () => {
    expect(maxGross([holding([seg("stock", "A", 0.5)])])).toBe(1);
  });
});
