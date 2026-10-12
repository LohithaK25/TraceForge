import { useEffect, useRef, useState } from "react";

import {
  getDetectionStatus,
  getIncident,
  getIncidentPage,
  IncidentApiError,
  type DetectionStatusResponse,
  type IncidentFilter,
  type IncidentRecord,
  type SourceFreshness,
} from "../api/incidents";
import { ServiceHealthPanel } from "./ServiceHealthPanel";
import { TraceEvidence } from "./TraceEvidence";

type RequestState = "loading" | "ready" | "error";

export function IncidentDashboard() {
  const [filter, setFilter] = useState<IncidentFilter>("OPEN");
  const [items, setItems] = useState<IncidentRecord[]>([]);
  const [listState, setListState] = useState<RequestState>("loading");
  const [listError, setListError] = useState<string>();
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string>();
  const [detectionStatus, setDetectionStatus] = useState<DetectionStatusResponse>();
  const [freshnessState, setFreshnessState] = useState<RequestState>("loading");
  const [freshnessError, setFreshnessError] = useState<string>();
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string>();
  const [selectedIncident, setSelectedIncident] = useState<IncidentRecord>();
  const [detailState, setDetailState] = useState<RequestState>("ready");
  const [detailError, setDetailError] = useState<string>();
  const moreController = useRef<AbortController | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    moreController.current?.abort();
    setListState("loading");
    setListError(undefined);
    setItems([]);
    setNextCursor(null);
    setMoreError(undefined);
    setSelectedIncidentId(undefined);
    setSelectedIncident(undefined);
    setDetailError(undefined);

    getIncidentPage(filter, undefined, controller.signal)
      .then((page) => {
        setItems(page.items);
        setNextCursor(page.nextCursor);
        setListState("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setListError(errorMessage(error, "Incidents could not be loaded."));
        setListState("error");
      });

    return () => {
      controller.abort();
      moreController.current?.abort();
    };
  }, [filter, refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    setFreshnessState("loading");
    setFreshnessError(undefined);
    setDetectionStatus(undefined);

    getDetectionStatus(controller.signal)
      .then((status) => {
        setDetectionStatus(status);
        setFreshnessState("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setFreshnessError(errorMessage(error, "Detection freshness could not be loaded."));
        setFreshnessState("error");
      });

    return () => controller.abort();
  }, [refreshKey]);

  useEffect(() => {
    if (!selectedIncidentId) return;
    const controller = new AbortController();
    setDetailState("loading");
    setDetailError(undefined);
    setSelectedIncident(undefined);

    getIncident(selectedIncidentId, controller.signal)
      .then((incident) => {
        setSelectedIncident(incident);
        setDetailState("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setDetailError(errorMessage(error, "Incident details could not be loaded."));
        setDetailState("error");
      });

    return () => controller.abort();
  }, [selectedIncidentId]);

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    const controller = new AbortController();
    moreController.current = controller;
    setLoadingMore(true);
    setMoreError(undefined);
    try {
      const page = await getIncidentPage(filter, nextCursor, controller.signal);
      setItems((current) => [...current, ...page.items]);
      setNextCursor(page.nextCursor);
    } catch (error) {
      if (!controller.signal.aborted) setMoreError(errorMessage(error, "More incidents could not be loaded."));
    } finally {
      if (moreController.current === controller) {
        moreController.current = undefined;
        setLoadingMore(false);
      }
    }
  }

  function showFilter(nextFilter: IncidentFilter) {
    if (nextFilter === filter) return;
    setSelectedIncidentId(undefined);
    setFilter(nextFilter);
  }

  function toggleDetails(id: string) {
    setSelectedIncidentId((current) => (current === id ? undefined : id));
  }

  return (
    <section className="incident-dashboard" aria-label="Incident dashboard">
      <div className="dashboard-toolbar">
        <p>Incident findings and collection freshness are reported separately.</p>
        <button className="button button--quiet" type="button" onClick={() => setRefreshKey((key) => key + 1)}>
          Refresh data
        </button>
      </div>

      <ServiceHealthPanel state={freshnessState} data={detectionStatus} error={freshnessError} />

      <DetectionFreshness
        state={freshnessState}
        data={detectionStatus}
        error={freshnessError}
      />

      <section className="incident-list-section" aria-labelledby="incident-list-title">
        <div className="incident-list-heading">
          <div>
            <span className="section-kicker">DETERMINISTIC FINDINGS</span>
            <h3 id="incident-list-title">Incidents</h3>
          </div>
          <div className="incident-controls" role="group" aria-label="Incident history filter">
            <button
              className={`filter-button${filter === "OPEN" ? " filter-button--selected" : ""}`}
              type="button"
              aria-pressed={filter === "OPEN"}
              onClick={() => showFilter("OPEN")}
            >
              Open
            </button>
            <button
              className={`filter-button${filter === "RESOLVED" ? " filter-button--selected" : ""}`}
              type="button"
              aria-pressed={filter === "RESOLVED"}
              onClick={() => showFilter("RESOLVED")}
            >
              Resolved history
            </button>
          </div>
        </div>

        {listState === "loading" && <p className="state-panel" role="status">Loading {filter.toLowerCase()} incidents…</p>}
        {listState === "error" && (
          <div className="state-panel state-panel--error" role="alert">
            <strong>Incident results are unavailable.</strong>
            <span>{listError}</span>
            <span>An API error is not an empty incident list.</span>
            <button className="button button--quiet" type="button" onClick={() => setRefreshKey((key) => key + 1)}>
              Try again
            </button>
          </div>
        )}
        {listState === "ready" && items.length === 0 && (
          <div className="state-panel state-panel--empty" role="status">
            <strong>{filter === "OPEN" ? "No open incidents were returned." : "No resolved incidents were returned."}</strong>
            <span>This is an empty result for this filter, not confirmation that every detection source is healthy.</span>
          </div>
        )}
        {listState === "ready" && items.length > 0 && (
          <div className="incident-list">
            {items.map((incident) => (
              <IncidentCard
                key={incident.id}
                incident={incident}
                expanded={selectedIncidentId === incident.id}
                onToggleDetails={() => toggleDetails(incident.id)}
              />
            ))}
          </div>
        )}

        {moreError && <p className="inline-error" role="alert">{moreError}</p>}
        {listState === "ready" && nextCursor && (
          <button className="button button--load-more" type="button" disabled={loadingMore} onClick={loadMore}>
            {loadingMore ? "Loading more…" : "Load more"}
          </button>
        )}
      </section>

      {selectedIncidentId && (
        <IncidentDetail
          incident={selectedIncident}
          state={detailState}
          error={detailError}
          onClose={() => setSelectedIncidentId(undefined)}
        />
      )}
    </section>
  );
}

function DetectionFreshness({
  state,
  data,
  error,
}: {
  state: RequestState;
  data?: DetectionStatusResponse;
  error?: string;
}) {
  return (
    <section className="freshness-panel" aria-labelledby="freshness-title">
      <div className="freshness-heading">
        <div>
          <span className="section-kicker">COLLECTION STATUS</span>
          <h3 id="freshness-title">Detection-source freshness</h3>
        </div>
        {state === "ready" && data && <StatusBadge value={data.status} />}
      </div>

      {state === "loading" && <p role="status" className="freshness-message">Loading detection freshness…</p>}
      {state === "error" && (
        <p role="alert" className="freshness-message freshness-message--error">
          Freshness could not be confirmed. {error}
        </p>
      )}
      {state === "ready" && data && (
        <>
          <p className={`freshness-message${data.status === "CURRENT" && data.sources.length > 0 && data.sources.every((source) => source.status === "CURRENT") ? " freshness-message--current" : " freshness-message--caution"}`}>
            {freshnessDescription(data)}
          </p>
          {data.latestCycle && (
            <p className="cycle-meta">
              Latest cycle: {data.latestCycle.status.toLowerCase()} · completed {formatTimestamp(data.latestCycle.completedAt)}
            </p>
          )}
          {data.sources.length === 0 ? (
            <p className="source-empty">No source observations were returned.</p>
          ) : (
            <ul className="source-list">
              {data.sources.map((source) => <SourceRow key={source.source} source={source} />)}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function SourceRow({ source }: { source: SourceFreshness }) {
  return (
    <li className="source-row">
      <div className="source-row__top">
        <span className="source-name">{source.source}</span>
        <StatusBadge value={source.status} />
      </div>
      <p>
        Last successful observation: {source.lastSuccessAt ? formatTimestamp(source.lastSuccessAt) : "none recorded"}
        <span className="source-row__separator"> · </span>
        Attempted: {formatTimestamp(source.attemptedAt)}
      </p>
      {source.errorCode && <code className="source-error-code">{source.errorCode}</code>}
    </li>
  );
}

function IncidentCard({
  incident,
  expanded,
  onToggleDetails,
}: {
  incident: IncidentRecord;
  expanded: boolean;
  onToggleDetails: () => void;
}) {
  return (
    <article className="incident-card">
      <div className="incident-card__topline">
        <span className="rule-label">{formatRule(incident.ruleKey)}</span>
        <div className="badge-group">
          <StatusBadge value={incident.severity} />
          <StatusBadge value={incident.status} />
        </div>
      </div>
      <h4>{incident.summary}</h4>
      <p className="incident-resource">Affected {incident.scopeType === "SERVICE" ? "service" : "order recovery"}: {incident.scopeType === "SERVICE" ? incident.sourceReference : "Order workflow"}</p>
      <dl className="incident-meta">
        <div><dt>First observed</dt><dd>{formatTimestamp(incident.firstSeenAt)}</dd></div>
        <div><dt>Last observed</dt><dd>{formatTimestamp(incident.lastSeenAt)}</dd></div>
        <div><dt>Occurrences</dt><dd>{incident.occurrenceCount}</dd></div>
        {incident.resolvedAt && <div><dt>Resolved</dt><dd>{formatTimestamp(incident.resolvedAt)}</dd></div>}
      </dl>
      <button className="details-button" type="button" aria-expanded={expanded} onClick={onToggleDetails}>
        {expanded ? "Close details" : "View details"}
      </button>
    </article>
  );
}

function IncidentDetail({
  incident,
  state,
  error,
  onClose,
}: {
  incident?: IncidentRecord;
  state: RequestState;
  error?: string;
  onClose: () => void;
}) {
  const traceIds = incident
    ? [...new Set([incident.originTraceId, ...incident.evidence.map((evidence) => evidence.traceId)].filter((id): id is string => id !== null))]
    : [];
  return (
    <section className="detail-panel" aria-label="Selected incident details" aria-live="polite">
      <div className="detail-heading">
        <h3>Incident details</h3>
        <button className="details-button" type="button" onClick={onClose}>Close</button>
      </div>
      {state === "loading" && <p role="status">Loading incident details…</p>}
      {state === "error" && <p role="alert" className="inline-error">{error}</p>}
      {state === "ready" && incident && (
        <>
          <p className="detail-summary">{incident.summary}</p>
          <dl className="detail-meta">
            <div><dt>Incident ID</dt><dd className="mono-value">{incident.id}</dd></div>
            <div><dt>Rule</dt><dd>{incident.ruleKey} · version {incident.ruleVersion}</dd></div>
            <div><dt>Affected resource</dt><dd>{incident.scopeType} · {incident.sourceReference}</dd></div>
            <div><dt>Created</dt><dd>{formatTimestamp(incident.createdAt)}</dd></div>
            <div><dt>Last evaluated</dt><dd>{formatTimestamp(incident.lastEvaluatedAt)}</dd></div>
            {incident.originTraceId && <div><dt>Origin trace ID</dt><dd className="mono-value">{incident.originTraceId}</dd></div>}
          </dl>
          <h4>Evidence returned by the API</h4>
          {incident.evidence.length === 0 ? (
            <p className="detail-empty">No evidence references were returned for this incident.</p>
          ) : (
            <ul className="evidence-list">
              {incident.evidence.map((evidence, index) => (
                <li key={`${evidence.sourceType}-${evidence.sourceId}-${evidence.observedAt}-${index}`}>
                  <strong>{evidence.sourceType}</strong>
                  <span>{evidence.signalCode}</span>
                  <time dateTime={evidence.observedAt}>{formatTimestamp(evidence.observedAt)}</time>
                  {evidence.traceId && <code className="mono-value">Trace {evidence.traceId}</code>}
                </li>
              ))}
            </ul>
          )}
          <h4>Trace evidence from Tempo</h4>
          {traceIds.length === 0 ? (
            <p className="detail-empty">No trace references were returned for this incident.</p>
          ) : (
            <div className="trace-evidence-list">
              {traceIds.map((traceId) => <TraceEvidence key={traceId} traceId={traceId} />)}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function StatusBadge({ value }: { value: string }) {
  return <span className={`status-badge status-badge--${value.toLowerCase().replaceAll("_", "-")}`}>{value.replaceAll("_", " ")}</span>;
}

function freshnessDescription(data: DetectionStatusResponse): string {
  if (data.status === "NOT_RUN") return "Detection has not completed yet; service health is not confirmed.";
  if (data.status === "UNAVAILABLE") return "Detection status is unavailable; service health is not confirmed.";
  if (data.status === "STALE") return "The last successful observations are stale; current service health is not confirmed.";
  if (data.status === "PARTIAL") return "Some detection inputs are incomplete; incident results may be partial.";
  if (data.sources.length === 0) return "No source observations were returned; current service health cannot be confirmed.";
  if (data.sources.some((source) => source.status !== "CURRENT")) return "At least one detection source is not current; review source status before treating results as complete.";
  return "The latest detection cycle and its sources are within the reported freshness window.";
}

function formatRule(ruleKey: IncidentRecord["ruleKey"]): string {
  return ruleKey === "SERVICE_NOT_READY" ? "Service not ready" : "Order recovery stalled";
}

function formatTimestamp(value: string | null): string {
  if (!value) return "not available";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "time unavailable" : parsed.toLocaleString();
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof IncidentApiError) return error.message;
  return fallback;
}
