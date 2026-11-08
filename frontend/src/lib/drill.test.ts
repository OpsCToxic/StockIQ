import { describe, expect, it } from "vitest";
import type { ExposureBar, Holding, Segment } from "../api/types";
import { companyRows, companySources, foldSegments, isDirectStock, kindTotals, swapSource } from "./drill";

function seg(kind: Segment["kind"], label: string, value: number, extra: Partial<Segment> = {}): Segment {
  return { kind, label, value: String(value), share: String(value / 10000), provisional: false, ...extra } as Segment;
}

function holding(id: number, ticker: string, segments: Segment[]): Holding {
  return { holding_id: id, holding: ticker, name: ticker, value: "10000", share: "0.5", report_as_of: null, segments };
}

const tsll = holding(1, "TSLL", [
  seg("stock", "Tesla, Inc.", 1500, { edge_id: 10 }),
  seg("cash", "Goldman", 4000),
  seg("cash", "Dreyfus", 3500),
  seg("swap_owed", "Citibank: swap on TSLA", -550, { edge_id: 20 }),
  seg("swap_owed", "BofA: swap on TSLA", -200, { edge_id: 20 }),
  seg("other", "Other, net", -180),
]);

const voo = holding(2, "VOO", [
  seg("stock", "NVIDIA CORP", 700, { edge_id: 30 }),
  seg("stock", "Tesla, Inc.", 150, { edge_id: 31, provisional: true }),
  seg("stock", "Other companies (390)", 5000),
  seg("unmatched", "Equity not matched to a company", 140),
  seg("cash", "Vanguard Market Liquidity Fund", 30),
]);

const uuuu = holding(3, "UUUU", [seg("stock", "ENERGY FUELS INC", 600)]);

describe("kindTotals", () => {
  it("adds each kind up, with what is owed as a positive magnitude", () => {
    expect(kindTotals(tsll)).toEqual({ stock: 1500, cash: 7500, unmatched: 0, owed: 750, other: -180 });
  });
});

describe("isDirectStock", () => {
  it("is true for a single-company position and false for a fund", () => {
    expect(isDirectStock(uuuu)).toBe(true);
    expect(isDirectStock(voo)).toBe(false);
  });
});

describe("companySources", () => {
  it("finds every holding that carries the company, direct first then funds by value", () => {
    const sources = companySources("Tesla, Inc.", [voo, tsll, uuuu]);
    expect(sources.map((s) => [s.holding, s.via, s.value])).toEqual([
      ["TSLL", "fund", 1500],
      ["VOO", "fund", 150],
    ]);
    expect(sources[1]!.provisional).toBe(true);
    expect(companySources("ENERGY FUELS INC", [voo, tsll, uuuu])[0]!.via).toBe("direct");
  });

  it("is empty for a company no holding carries", () => {
    expect(companySources("Nobody", [voo])).toEqual([]);
  });
});

describe("swapSource", () => {
  const bar = (edge: number | null): ExposureBar =>
    ({ company_id: 1, name: "Tesla, Inc.", funded: "0", swap: "0", funded_share: "0", swap_share: "0", total_share: "0", swap_edge_id: edge }) as ExposureBar;

  it("is the holding whose swap cites the same edge", () => {
    expect(swapSource(bar(20), [voo, tsll])?.holding).toBe("TSLL");
    expect(swapSource(bar(null), [voo, tsll])).toBeUndefined();
  });
});

describe("foldSegments", () => {
  it("keeps the largest companies, folds the rest with the server's fold, and keeps the other parts", () => {
    const folded = foldSegments(voo.segments, 1);
    expect(folded.map((s) => s.label)).toEqual([
      "NVIDIA CORP",
      "391 more companies",
      "Equity not matched to a company",
      "Vanguard Market Liquidity Fund",
    ]);
    expect(Number(folded[1]!.value)).toBe(150 + 5000);
  });

  it("changes nothing when every company already fits", () => {
    expect(foldSegments(tsll.segments)).toBe(tsll.segments);
  });
});

describe("companyRows", () => {
  it("ranks named companies by value and keeps the server's fold separate", () => {
    const { named, other } = companyRows(voo.segments);
    expect(named.map((r) => r.label)).toEqual(["NVIDIA CORP", "Tesla, Inc."]);
    expect(other?.label).toBe("Other companies (390)");
    expect(other?.value).toBe(5000);
  });

  it("has no fold when the server sent every company", () => {
    expect(companyRows(uuuu.segments).other).toBeNull();
  });
});
