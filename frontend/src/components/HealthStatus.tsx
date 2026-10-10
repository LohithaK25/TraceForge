import type { ApiHealth } from "../api/health";

type HealthStatusProps = {
  state: "loading" | "ready" | "unavailable";
  health?: ApiHealth;
};

export function HealthStatus({ state, health }: HealthStatusProps) {
  if (state === "loading") {
    return <p className="health-state" role="status">Checking API connection…</p>;
  }

  if (state === "unavailable") {
    return (
      <p className="health-state health-state--error" role="status">
        API unavailable. Start the gateway to load live service state.
      </p>
    );
  }

  return (
    <p className="health-state health-state--ready" role="status">
      <span className="status-dot" aria-hidden="true" />
      {health?.service ?? "API"} responding · checked {formatTime(health?.timestamp)}
    </p>
  );
}

function formatTime(timestamp?: string): string {
  if (!timestamp) return "time unavailable";
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime())
    ? "time unavailable"
    : parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
