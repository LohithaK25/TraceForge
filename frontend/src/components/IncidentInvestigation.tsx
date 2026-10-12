import { useEffect, useState } from "react";

import {
  getLatestInvestigation,
  InvestigationApiError,
  runInvestigation,
  type InvestigationClaim,
  type InvestigationResult,
} from "../api/investigations";

type ViewState = "loading" | "empty" | "ready" | "running" | "error";

export function IncidentInvestigation({ incidentId }: { incidentId: string }) {
  const [state, setState] = useState<ViewState>("loading");
  const [result, setResult] = useState<InvestigationResult>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    const controller = new AbortController();
    setState("loading");
    setResult(undefined);
    setError(undefined);
    getLatestInvestigation(incidentId, controller.signal)
      .then((latest) => {
        setResult(latest);
        setState(latest ? "ready" : "empty");
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(errorMessage(cause));
        setState("error");
      });
    return () => controller.abort();
  }, [incidentId]);

  async function investigate() {
    setState("running");
    setError(undefined);
    try {
      const next = await runInvestigation(incidentId);
      setResult(next);
      setState("ready");
    } catch (cause) {
      setError(errorMessage(cause));
      setState("error");
    }
  }

  return (
    <section className="investigation-panel" aria-labelledby="investigation-title" aria-live="polite">
      <div className="investigation-panel__heading">
        <div>
          <span className="section-kicker">EVIDENCE-BASED REVIEW</span>
          <h4 id="investigation-title">Investigation</h4>
        </div>
        {(state === "empty" || state === "ready" || state === "error") && (
          <button className="button button--quiet" type="button" onClick={investigate}>
            {result ? "Refresh investigation" : "Run investigation"}
          </button>
        )}
      </div>

      {state === "loading" && <p className="freshness-message" role="status">Loading the saved investigation…</p>}
      {state === "running" && <p className="freshness-message" role="status">Collecting bounded evidence and preparing a deterministic report…</p>}
      {state === "empty" && (
        <div className="state-panel state-panel--empty" role="status">
          <strong>No investigation has been saved for this incident.</strong>
          <span>Run an investigation to collect current owning-service evidence. No findings are generated in advance.</span>
        </div>
      )}
      {state === "error" && (
        <div className="state-panel state-panel--error" role="alert">
          <strong>Investigation data is unavailable.</strong>
          <span>{error}</span>
          <span>A failed request does not mean the incident is resolved or its sources are healthy.</span>
        </div>
      )}
      {state === "ready" && result && <InvestigationReport result={result} />}
    </section>
  );
}

function InvestigationReport({ result }: { result: InvestigationResult }) {
  const evidenceById = new Map(result.evidence.map((item) => [item.evidenceId, item]));
  return (
    <div className="investigation-report">
      <div className="investigation-report__status">
        <span className={`status-badge status-badge--${result.status.toLowerCase()}`}>{result.status}</span>
        <span>{result.provider}</span>
        <time dateTime={result.generatedAt}>Generated {formatTimestamp(result.generatedAt)}</time>
      </div>
      <p className="detail-summary">{result.summary}</p>
      <p className="investigation-uncertainty" role="note"><strong>Uncertainty:</strong> {result.uncertainty}</p>
      <ClaimSection title="Observed facts" claims={result.facts} evidenceById={evidenceById} />
      <ClaimSection title="Possible explanations" claims={result.hypotheses} evidenceById={evidenceById} />
      <ClaimSection title="Suggested next steps" claims={result.recommendedActions} evidenceById={evidenceById} />

      <section className="investigation-subsection" aria-label="Evidence gaps">
        <h5>Evidence gaps and limitations</h5>
        {result.evidenceGaps.length === 0 ? (
          <p className="detail-empty">No collection gaps were reported for this run.</p>
        ) : (
          <ul className="investigation-gap-list">
            {result.evidenceGaps.map((gap, index) => (
              <li key={`${gap.source}-${gap.code}-${index}`}>
                <strong>{gap.source} · {gap.code}</strong>
                <span>{gap.required ? "Required signal" : "Optional supporting signal"}</span>
                <p>{gap.summary}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="investigation-subsection" aria-label="Investigation source freshness">
        <h5>Source freshness for this investigation</h5>
        {result.sources.length === 0 ? (
          <p className="detail-empty">No external sources were queried; only the persisted incident record is shown.</p>
        ) : (
          <ul className="source-list">
            {result.sources.map((source) => (
              <li className="source-row" key={source.source}>
                <div className="source-row__top">
                  <span className="source-name">{source.source}</span>
                  <span className={`status-badge status-badge--${source.status.toLowerCase()}`}>{source.status}</span>
                </div>
                <p>Last successful observation: {source.lastSuccessAt ? formatTimestamp(source.lastSuccessAt) : "none recorded"} · Attempted: {formatTimestamp(source.attemptedAt)}</p>
                {source.errorCode && <code className="source-error-code">{source.errorCode}</code>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="investigation-subsection" aria-label="Collected evidence">
        <h5>Collected evidence</h5>
        <ul className="investigation-evidence-list">
          {result.evidence.map((item) => (
            <li id={evidenceAnchor(item.evidenceId)} key={item.evidenceId}>
              <div className="investigation-evidence-list__heading">
                <strong>{item.sourceType}</strong>
                {item.signalCode && <code>{item.signalCode}</code>}
              </div>
              <p>{item.summary}</p>
              <small>{item.sourceName} · {item.observedAt ? formatTimestamp(item.observedAt) : "observation time unavailable"}</small>
              {item.freshnessStatus && <small>Freshness: {item.freshnessStatus}</small>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function ClaimSection({
  title,
  claims,
  evidenceById,
}: {
  title: string;
  claims: InvestigationClaim[];
  evidenceById: Map<string, InvestigationResult["evidence"][number]>;
}) {
  return (
    <section className="investigation-subsection">
      <h5>{title}</h5>
      {claims.length === 0 ? (
        <p className="detail-empty">No {title.toLowerCase()} were produced from the available evidence.</p>
      ) : (
        <ul className="investigation-claim-list">
          {claims.map((claim) => (
            <li key={claim.claimId}>
              <p>{claim.text}</p>
              <span className="claim-citations">Evidence: {claim.evidenceIds.map((id, index) => {
                const evidence = evidenceById.get(id);
                return evidence ? (
                  <span key={id}>{index > 0 ? ", " : ""}<a href={`#${evidenceAnchor(id)}`}>{evidence.sourceType} {evidence.signalCode ?? "record"}</a></span>
                ) : null;
              })}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function evidenceAnchor(id: string): string {
  return `investigation-evidence-${id.replaceAll(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "time unavailable" : parsed.toLocaleString();
}

function errorMessage(error: unknown): string {
  if (error instanceof InvestigationApiError) return error.message;
  return "The investigation could not be completed.";
}
