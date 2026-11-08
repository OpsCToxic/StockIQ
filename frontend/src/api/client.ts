import type { EvidenceResponse, ExposureResponse } from "./types";

// In development Vite proxies /api to the FastAPI backend on 127.0.0.1:8000.
const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(BASE + path);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep the status text
    }
    throw new Error(`${response.status}: ${detail}`);
  }
  return (await response.json()) as T;
}

export function fetchExposure(
  asOf?: string,
  top = 15,
  expand: number[] = [],
): Promise<ExposureResponse> {
  const query = new URLSearchParams({ top: String(top) });
  if (asOf) query.set("as_of", asOf);
  for (const id of expand) query.append("expand", String(id));
  return get<ExposureResponse>(`/portfolio/exposure?${query.toString()}`);
}

export function fetchEvidence(edgeId: number): Promise<EvidenceResponse> {
  return get<EvidenceResponse>(`/edges/${edgeId}/evidence`);
}
