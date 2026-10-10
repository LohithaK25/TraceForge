export type ApiHealth = {
  status: string;
  service: string;
  timestamp: string;
};

export async function getApiHealth(signal?: AbortSignal): Promise<ApiHealth> {
  const response = await fetch("/api/v1/health", { signal });
  if (!response.ok) {
    throw new Error(`Health endpoint returned HTTP ${response.status}`);
  }

  const payload: unknown = await response.json();
  if (!isApiHealth(payload)) {
    throw new Error("Health endpoint returned an unexpected response");
  }
  return payload;
}

function isApiHealth(value: unknown): value is ApiHealth {
  if (typeof value !== "object" || value === null) return false;
  const health = value as Record<string, unknown>;
  return (
    typeof health.status === "string" &&
    typeof health.service === "string" &&
    typeof health.timestamp === "string"
  );
}
