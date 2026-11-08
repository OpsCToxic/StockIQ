import { useEffect, useRef, useState } from "react";
import { fetchEvidence } from "../api/client";
import type { EvidenceResponse } from "../api/types";
import { dateLabel, percent } from "../lib/format";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; data: EvidenceResponse };

const SOURCE_NAMES: Record<string, string> = {
  nport: "SEC N-PORT",
  sec_sic: "SEC company record",
};

const EDGE_WORDS: Record<string, string> = {
  CONTAINS: "holds",
  SYNTHETIC: "has swap exposure to",
  IN_SECTOR: "is classified in",
};

interface Props {
  edgeId: number;
  onClose: () => void;
}

/** The filing text behind a part, in a drawer over the page. Escape or the backdrop closes it. */
export function EvidenceDrawer({ edgeId, onClose }: Props) {
  const [state, setState] = useState<State>({ status: "loading" });
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchEvidence(edgeId)
      .then((data) => {
        if (!cancelled) setState({ status: "ok", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [edgeId]);

  useEffect(() => {
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-h">
        <div className="drawer-head">
          <h2 id="evidence-h">Filed evidence</h2>
          <button type="button" ref={closeButton} onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {state.status === "loading" && <p className="muted">Loading the filing text…</p>}
        {state.status === "error" && <p className="error">Could not load evidence: {state.message}</p>}
        {state.status === "ok" && (
          <>
            <p className="lead">
              <b>{state.data.from_entity}</b> {EDGE_WORDS[state.data.edge_type] ?? state.data.edge_type}{" "}
              <b>{state.data.to_entity}</b>
            </p>
            <dl className="facts">
              {state.data.weight != null && (
                <>
                  <dt>Weight</dt>
                  <dd>{percent(state.data.weight, 2)} of the fund's net assets</dd>
                </>
              )}
              <dt>Match confidence</dt>
              <dd>{Number(state.data.confidence).toFixed(2)}</dd>
              <dt>Known from</dt>
              <dd>{dateLabel(state.data.known_at)}</dd>
            </dl>
            <p className="muted">
              {state.data.total} source {state.data.total === 1 ? "line" : "lines"}
              {state.data.total > state.data.evidence.length ? `, showing ${state.data.evidence.length}` : ""}. Text is quoted exactly as filed.
            </p>
            <ul className="evidence-list">
              {state.data.evidence.map((e, i) => (
                <li key={`${e.doc_id}-${i}`}>
                  <a href={e.url} target="_blank" rel="noreferrer">
                    {SOURCE_NAMES[e.source] ?? e.source} filing
                    {e.published_at ? `, public ${dateLabel(e.published_at)}` : ""}
                  </a>
                  {e.section && <span className="muted"> · {e.section}</span>}
                  {e.span_text && <pre>{e.span_text}</pre>}
                </li>
              ))}
            </ul>
          </>
        )}
      </aside>
    </>
  );
}
