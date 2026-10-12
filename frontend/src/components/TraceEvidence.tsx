import { useEffect, useRef, useState } from "react";

import { getTraceSummary, TraceApiError, type TraceSummary } from "../api/traces";

type LoadState = "idle" | "loading" | "ready" | "error";

export function TraceEvidence({ traceId }: { traceId: string }) {
  const [state, setState] = useState<LoadState>("idle");
  const [summary, setSummary] = useState<TraceSummary>();
  const [error, setError] = useState<string>();
  const controller = useRef<AbortController | undefined>(undefined);

  useEffect(() => () => controller.current?.abort(), []);

  async function loadTrace() {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setState("loading");
    setError(undefined);
    setSummary(undefined);
    try {
      const result = await getTraceSummary(traceId, request.signal);
      if (!request.signal.aborted) {
        setSummary(result);
        setState("ready");
      }
    } catch (cause) {
      if (!request.signal.aborted) {
        setError(cause instanceof TraceApiError ? cause.message : "Trace evidence could not be loaded.");
        setState("error");
      }
    }
  }

  return (
    <div className="trace-evidence">
      <div className="trace-evidence__heading">
        <code className="mono-value">{traceId}</code>
        <button className="details-button" type="button" disabled={state === "loading"} onClick={loadTrace}>
          {state === "loading" ? "Loading trace…" : state === "ready" ? "Reload trace" : "Load trace"}
        </button>
      </div>
      {state === "error" && <p className="inline-error" role="alert">{error}</p>}
      {state === "ready" && summary && (
        <div className="trace-summary" aria-label={`Trace with ${summary.spans.length} spans`}>
          <p>{summary.spans.length} spans from {uniqueServices(summary).join(", ") || "unknown services"}</p>
          {summary.truncated && <p className="trace-caution">Showing the first 250 spans returned by the bounded trace API.</p>}
          <ol className="trace-span-list">
            {summary.spans.map((span) => (
              <li key={`${span.service}-${span.spanId}`} className="trace-span-row">
                <div className="trace-span-row__top">
                  <strong>{span.service}</strong>
                  <span className={`status-badge status-badge--${span.status.toLowerCase()}`}>{span.status}</span>
                </div>
                <span className="trace-span-name">{span.name}</span>
                <span className="trace-span-meta">
                  {span.httpMethod && `${span.httpMethod} `}{span.httpRoute ?? ""}
                  {span.httpStatusCode !== null && ` · HTTP ${span.httpStatusCode}`}
                  {span.parentSpanId && ` · parent ${span.parentSpanId}`}
                </span>
                <time dateTime={span.startTime ?? undefined}>{formatTimestamp(span.startTime)}</time>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function uniqueServices(summary: TraceSummary): string[] {
  return [...new Set(summary.spans.map((span) => span.service))];
}

function formatTimestamp(value: string | null): string {
  if (!value) return "time unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "time unavailable" : parsed.toLocaleString();
}
