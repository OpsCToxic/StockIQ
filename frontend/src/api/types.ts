import type { components } from "./schema";

// Types come from the API's OpenAPI spec (npm run gen:api), so they cannot drift from the backend.
type S = components["schemas"];

export type ExposureResponse = S["ExposureResponse"];
export type EvidenceResponse = S["EvidenceResponse"];
export type Holding = S["HoldingOut"];
export type Segment = S["SegmentOut"];
export type ExposureBar = S["ExposureBarOut"];
export type Line = S["Line"];
export type BreakdownPart = S["BreakdownOut"];
export type BreakdownItem = S["BreakdownItemOut"];
export type Flag = S["FlagOut"];
export type Herfindahl = S["HerfindahlOut"];
