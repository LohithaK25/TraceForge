import type { DetectionStatusResponse, ServiceHealthSnapshot } from "../api/incidents";

type RequestState = "loading" | "ready" | "error";

export function ServiceHealthPanel({
  state,
  data,
  error,
}: {
  state: RequestState;
  data?: DetectionStatusResponse;
  error?: string;
}) {
  return (
    <section className="service-health-panel" aria-labelledby="service-health-title">
      <div className="service-health-panel__heading">
        <div>
          <span className="section-kicker">LAST READINESS OBSERVATIONS</span>
          <h3 id="service-health-title">Service health</h3>
        </div>
      </div>
      <p className="service-health-note">
        Persisted probe results are shown with collection freshness; they are not a new live health check.
      </p>
      {state === "loading" && <p className="state-panel" role="status">Loading service health observations…</p>}
      {state === "error" && (
        <p className="state-panel state-panel--error" role="alert">
          {error ?? "Service health observations are unavailable; current health is not confirmed."}
        </p>
      )}
      {state === "ready" && data && (
        <ul className="service-health-list">
          {data.services.map((service) => <ServiceHealthRow key={service.serviceName} service={service} />)}
        </ul>
      )}
    </section>
  );
}

function ServiceHealthRow({ service }: { service: ServiceHealthSnapshot }) {
  return (
    <li className="service-health-row">
      <div className="service-health-row__top">
        <strong>{service.serviceName}</strong>
        <div className="badge-group">
          <StatusBadge value={service.status} />
          <StatusBadge value={service.freshnessStatus} />
        </div>
      </div>
      <p>Last probe: {service.observedAt ? formatTimestamp(service.observedAt) : "none recorded"}</p>
      {service.incidentOpen && <span className="service-health-incident">A service-not-ready incident is open.</span>}
      {(service.status !== "UP" || service.freshnessStatus !== "CURRENT") && (
        <span className="service-health-caution">Current readiness is not confirmed.</span>
      )}
    </li>
  );
}

function StatusBadge({ value }: { value: string }) {
  return <span className={`status-badge status-badge--${value.toLowerCase().replaceAll("_", "-")}`}>{value.replaceAll("_", " ")}</span>;
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "time unavailable" : parsed.toLocaleString();
}
