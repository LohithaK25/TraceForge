export type IncidentFilter = "OPEN" | "RESOLVED";
export type IncidentStatus = IncidentFilter;
export type RuleKey = "SERVICE_NOT_READY" | "ORDER_RECOVERY_STALLED";
export type FreshnessStatus = "CURRENT" | "PARTIAL" | "STALE" | "UNAVAILABLE";
export type DetectionStatus = "NOT_RUN" | "CURRENT" | "PARTIAL" | "STALE" | "UNAVAILABLE";

export type EvidenceReference = {
  sourceType: "HEALTH_PROBE" | "ORDER_RECOVERY";
  sourceId: string;
  observedAt: string;
  signalCode: string;
  traceId: string | null;
};

export type IncidentRecord = {
  id: string;
  ruleKey: RuleKey;
  ruleVersion: number;
  severity: "HIGH" | "CRITICAL";
  status: IncidentStatus;
  fingerprint: string;
  scopeType: "SERVICE" | "ORDER";
  sourceReference: string;
  firstSeenAt: string;
  lastSeenAt: string;
  lastEvaluatedAt: string;
  resolvedAt: string | null;
  occurrenceCount: number;
  summary: string;
  evidence: EvidenceReference[];
  originTraceId: string | null;
  createdAt: string;
  updatedAt: string;
};

export type SourceFreshness = {
  source: string;
  status: FreshnessStatus;
  attemptedAt: string;
  lastSuccessAt: string | null;
  itemCount: number;
  errorCode: string | null;
};

export type DetectionCycle = {
  cycleId: string;
  startedAt: string;
  completedAt: string | null;
  status: "RUNNING" | "COMPLETE" | "PARTIAL" | "FAILED";
  findingsOpenedOrUpdated: number;
  incidentsResolved: number;
  failureCode: string | null;
};

export type DetectionStatusResponse = {
  status: DetectionStatus;
  latestCycle: DetectionCycle | null;
  sources: SourceFreshness[];
  services: ServiceHealthSnapshot[];
};

export type ServiceHealthSnapshot = {
  serviceName: "api-gateway" | "order-service" | "inventory-service" | "payment-service";
  status: "UP" | "DOWN" | "TIMEOUT" | "UNKNOWN";
  observedAt: string | null;
  freshnessStatus: FreshnessStatus;
  incidentOpen: boolean;
};

export type IncidentPage = {
  items: IncidentRecord[];
  limit: number;
  nextCursor: string | null;
  detectionStatus: DetectionStatusResponse;
};

export class IncidentApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "IncidentApiError";
  }
}

const FRESHNESS_STATUSES: FreshnessStatus[] = ["CURRENT", "PARTIAL", "STALE", "UNAVAILABLE"];
const DETECTION_STATUSES: DetectionStatus[] = ["NOT_RUN", ...FRESHNESS_STATUSES];

export async function getIncidentPage(
  status: IncidentFilter,
  cursor?: string,
  signal?: AbortSignal,
): Promise<IncidentPage> {
  const params = new URLSearchParams({ status, limit: "25" });
  if (cursor) params.set("cursor", cursor);
  return requestJson(`/api/v1/incidents?${params.toString()}`, isIncidentPage, signal);
}

export function getDetectionStatus(signal?: AbortSignal): Promise<DetectionStatusResponse> {
  return requestJson("/api/v1/detection-status", isDetectionStatus, signal);
}

export function getIncident(id: string, signal?: AbortSignal): Promise<IncidentRecord> {
  return requestJson(`/api/v1/incidents/${encodeURIComponent(id)}`, isIncidentRecord, signal);
}

async function requestJson<T>(
  path: string,
  isExpectedShape: (value: unknown) => value is T,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new IncidentApiError("The TraceForge API could not be reached.");
  }

  if (!response.ok) {
    if (response.status === 404) {
      throw new IncidentApiError("This incident is no longer available.", response.status);
    }
    if (response.status === 503) {
      throw new IncidentApiError("The detection store is unavailable; current data could not be confirmed.", response.status);
    }
    throw new IncidentApiError(`The TraceForge API returned HTTP ${response.status}.`, response.status);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new IncidentApiError("The TraceForge API returned an unreadable response.", response.status);
  }
  if (!isExpectedShape(payload)) {
    throw new IncidentApiError("The TraceForge API returned data in an unexpected format.", response.status);
  }
  return payload;
}

function isIncidentPage(value: unknown): value is IncidentPage {
  return (
    isRecord(value) &&
    Array.isArray(value.items) &&
    value.items.every(isIncidentRecord) &&
    isIntegerInRange(value.limit, 1, 100) &&
    isNullableString(value.nextCursor) &&
    isDetectionStatus(value.detectionStatus)
  );
}

function isIncidentRecord(value: unknown): value is IncidentRecord {
  return (
    isRecord(value) &&
    isString(value.id) &&
    (value.ruleKey === "SERVICE_NOT_READY" || value.ruleKey === "ORDER_RECOVERY_STALLED") &&
    isIntegerInRange(value.ruleVersion, 1, Number.MAX_SAFE_INTEGER) &&
    (value.severity === "HIGH" || value.severity === "CRITICAL") &&
    (value.status === "OPEN" || value.status === "RESOLVED") &&
    isString(value.fingerprint) &&
    (value.scopeType === "SERVICE" || value.scopeType === "ORDER") &&
    isString(value.sourceReference) &&
    isTimestamp(value.firstSeenAt) &&
    isTimestamp(value.lastSeenAt) &&
    isTimestamp(value.lastEvaluatedAt) &&
    isNullableTimestamp(value.resolvedAt) &&
    isIntegerInRange(value.occurrenceCount, 1, Number.MAX_SAFE_INTEGER) &&
    isString(value.summary) &&
    Array.isArray(value.evidence) &&
    value.evidence.length <= 20 &&
    value.evidence.every(isEvidenceReference) &&
    isNullableString(value.originTraceId) &&
    isTimestamp(value.createdAt) &&
    isTimestamp(value.updatedAt)
  );
}

function isEvidenceReference(value: unknown): value is EvidenceReference {
  return (
    isRecord(value) &&
    (value.sourceType === "HEALTH_PROBE" || value.sourceType === "ORDER_RECOVERY") &&
    isString(value.sourceId) &&
    isTimestamp(value.observedAt) &&
    isString(value.signalCode) &&
    isNullableString(value.traceId)
  );
}

function isDetectionStatus(value: unknown): value is DetectionStatusResponse {
  return (
    isRecord(value) &&
    typeof value.status === "string" &&
    DETECTION_STATUSES.includes(value.status as DetectionStatus) &&
    (value.latestCycle === null || isDetectionCycle(value.latestCycle)) &&
    Array.isArray(value.sources) &&
    value.sources.every(isSourceFreshness) &&
    isServiceHealthSnapshots(value.services)
  );
}

function isServiceHealthSnapshots(value: unknown): value is ServiceHealthSnapshot[] {
  return Array.isArray(value) &&
    value.length === 4 &&
    value.every(isServiceHealthSnapshot) &&
    new Set(value.map((service) => service.serviceName)).size === 4;
}

function isServiceHealthSnapshot(value: unknown): value is ServiceHealthSnapshot {
  return isRecord(value) &&
    (value.serviceName === "api-gateway" || value.serviceName === "order-service" ||
      value.serviceName === "inventory-service" || value.serviceName === "payment-service") &&
    (value.status === "UP" || value.status === "DOWN" || value.status === "TIMEOUT" || value.status === "UNKNOWN") &&
    isNullableTimestamp(value.observedAt) &&
    typeof value.freshnessStatus === "string" &&
    FRESHNESS_STATUSES.includes(value.freshnessStatus as FreshnessStatus) &&
    typeof value.incidentOpen === "boolean";
}

function isDetectionCycle(value: unknown): value is DetectionCycle {
  return (
    isRecord(value) &&
    isString(value.cycleId) &&
    isTimestamp(value.startedAt) &&
    isNullableTimestamp(value.completedAt) &&
    (value.status === "RUNNING" || value.status === "COMPLETE" || value.status === "PARTIAL" || value.status === "FAILED") &&
    isIntegerInRange(value.findingsOpenedOrUpdated, 0, Number.MAX_SAFE_INTEGER) &&
    isIntegerInRange(value.incidentsResolved, 0, Number.MAX_SAFE_INTEGER) &&
    isNullableString(value.failureCode)
  );
}

function isSourceFreshness(value: unknown): value is SourceFreshness {
  return (
    isRecord(value) &&
    isString(value.source) &&
    typeof value.status === "string" &&
    FRESHNESS_STATUSES.includes(value.status as FreshnessStatus) &&
    isTimestamp(value.attemptedAt) &&
    isNullableTimestamp(value.lastSuccessAt) &&
    isIntegerInRange(value.itemCount, 0, Number.MAX_SAFE_INTEGER) &&
    isNullableString(value.errorCode)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isTimestamp(value: unknown): value is string {
  return isString(value) && Number.isFinite(Date.parse(value));
}

function isNullableTimestamp(value: unknown): value is string | null {
  return value === null || isTimestamp(value);
}

function isIntegerInRange(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum && value <= maximum;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
