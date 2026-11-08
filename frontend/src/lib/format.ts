// The API sends money and shares as decimal strings so no precision is lost on the wire.
export function num(value: string | number): number {
  return typeof value === "number" ? value : Number(value);
}

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

export function money(value: string | number): string {
  return usd.format(num(value));
}

export function percent(share: string | number, digits = 1): string {
  return `${(num(share) * 100).toFixed(digits)}%`;
}

export function dateLabel(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
}

const compactUsd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 2,
});

/** Large filed amounts (a fund's own swaps and holdings run to billions): $1.23B, -$247M. */
export function compact(value: string | number): string {
  return compactUsd.format(num(value));
}
