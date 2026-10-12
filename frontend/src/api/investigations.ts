import type { FreshnessStatus, SourceFreshness } from "./incidents";

export type InvestigationStatus = "COMPLETE" | "PARTIAL" | "INSUFFICIENT";
export type EvidenceType = "INCIDENT" | "INCIDENT_SIGNAL" | "SERVICE_HEALTH" | "ORDER_RECOVERY" | "TRACE_SPAN";

export type EvidenceDetails = {
  ruleKey?: "SERVICE_NOT_READY" | "ORDER_RECOVERY_STALLED";
  ruleVersion?: number;
  severity?: "HIGH" | "CRITICAL";
  incidentStatus?: "OPEN" | "RESOLVED";
  scopeType?: "SERVICE" | "ORDER";
  occurrenceCount?: number;
  serviceName?: "api-gateway" | "order-service" | "inventory-service" | "payment-service";
  probeStatus?: "UP" | "DOWN" | "TIMEOUT" | "UNKNOWN";
  orderStatus?: "PENDING" | "INVENTORY_RESERVED" | "PAYMENT_AUTHORIZED" | "CONFIRMED" | "FAILED" | "COMPENSATION_REQUIRED";
  failureReason?: string;
  recoveryError?: string;
  recoveryAttempts?: number;
  nextRecoveryAt?: string;
  inventoryReleased?: boolean;
  traceId?: string;
  service?: string;
  spanId?: string;
  parentSpanId?: string;
  spanName?: string;
  spanStatus?: "OK" | "ERROR" | "UNSET";
  httpMethod?: string;
  httpRoute?: string;
  httpStatusCode?: number;
};

export type InvestigationEvidence = {
  evidenceId: string;
  sourceType: EvidenceType;
  sourceName: "incident-service" | "detection-store" | "order-service" | "tempo-via-gateway";
  sourceId: string;
  observedAt: string | null;
  freshnessStatus: FreshnessStatus | null;
  signalCode: string | null;
  summary: string;
  details: EvidenceDetails;
};

export type EvidenceGap = {
  source: "SERVICE_HEALTH" | "ORDER_RECOVERY" | "TRACE";
  code: string;
  summary: string;
  required: boolean;
};

export type InvestigationClaim = {
  claimId: string;
  text: string;
  evidenceIds: string[];
};

export type InvestigationResult = {
  investigationId: string;
  incidentId: string;
  generatedAt: string;
  status: InvestigationStatus;
  provider: "deterministic-v1";
  summary: string;
  uncertainty: string;
  facts: InvestigationClaim[];
  hypotheses: InvestigationClaim[];
  recommendedActions: InvestigationClaim[];
  evidence: InvestigationEvidence[];
  evidenceGaps: EvidenceGap[];
  sources: SourceFreshness[];
};

export class InvestigationApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "InvestigationApiError";
  }
}

export async function getLatestInvestigation(
  incidentId: string,
  signal?: AbortSignal,
): Promise<InvestigationResult | undefined> {
  const path = `/api/v1/incidents/${encodeURIComponent(incidentId)}/investigations/latest`;
  const response = await fetchResponse(path, "GET", signal);
  if (response.status === 404) {
    const payload: unknown = await readJson(response);
    if (isRecord(payload) && isRecord(payload.detail) && payload.detail.code === "INVESTIGATION_NOT_FOUND") {
      return undefined;
    }
    throw new InvestigationApiError("This incident is no longer available.", 404);
  }
  return parseResult(response);
}

export async function runInvestigation(incidentId: string): Promise<InvestigationResult> {
  const path = `/api/v1/incidents/${encodeURIComponent(incidentId)}/investigations`;
  return parseResult(await fetchResponse(path, "POST"));
}

async function fetchResponse(path: string, method: "GET" | "POST", signal?: AbortSignal): Promise<Response> {
  try {
    const response = await fetch(path, { method, signal, headers: { Accept: "application/json" } });
    if (response.ok || response.status === 404) return response;
    if (response.status === 503) {
      throw new InvestigationApiError("The investigation store or a required service is unavailable; evidence is not confirmed.", 503);
    }
    throw new InvestigationApiError(`The investigation API returned HTTP ${response.status}.`, response.status);
  } catch (error) {
    if (error instanceof InvestigationApiError) throw error;
    if (isAbortError(error)) throw error;
    throw new InvestigationApiError("The investigation API could not be reached.");
  }
}

async function parseResult(response: Response): Promise<InvestigationResult> {
  const payload = await readJson(response);
  if (!isInvestigationResult(payload)) {
    throw new InvestigationApiError("The investigation API returned data in an unexpected format.", response.status);
  }
  return payload;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json() as unknown;
  } catch {
    throw new InvestigationApiError("The investigation API returned unreadable data.", response.status);
  }
}

function isInvestigationResult(value: unknown): value is InvestigationResult {
  if (!isRecord(value) || !isString(value.investigationId) || !isString(value.incidentId) ||
      !isTimestamp(value.generatedAt) || !["COMPLETE", "PARTIAL", "INSUFFICIENT"].includes(String(value.status)) ||
      value.provider !== "deterministic-v1" || !isString(value.summary) || value.summary.length > 320 ||
      !isString(value.uncertainty) || value.uncertainty.length > 320 ||
      !Array.isArray(value.facts) || !value.facts.every(isClaim) || !Array.isArray(value.hypotheses) ||
      !value.hypotheses.every(isClaim) || !Array.isArray(value.recommendedActions) || !value.recommendedActions.every(isClaim) ||
      !Array.isArray(value.evidence) || value.evidence.length > 100 || !value.evidence.every(isEvidence) ||
      !Array.isArray(value.evidenceGaps) || value.evidenceGaps.length > 20 || !value.evidenceGaps.every(isEvidenceGap) ||
      !Array.isArray(value.sources) || value.sources.length > 10 || !value.sources.every(isSourceFreshness)) return false;

  const evidenceIds = new Set(value.evidence.map((item) => (item as InvestigationEvidence).evidenceId));
  if (evidenceIds.size !== value.evidence.length) return false;
  const claims = [...value.facts, ...value.hypotheses, ...value.recommendedActions] as InvestigationClaim[];
  return claims.every((claim) => claim.evidenceIds.every((id) => evidenceIds.has(id)));
}

function isClaim(value: unknown): value is InvestigationClaim {
  return isRecord(value) && isString(value.claimId) && isString(value.text) && value.text.length <= 320 &&
    Array.isArray(value.evidenceIds) && value.evidenceIds.length > 0 && value.evidenceIds.length <= 20 &&
    value.evidenceIds.every(isString);
}

function isEvidence(value: unknown): value is InvestigationEvidence {
  return isRecord(value) && isString(value.evidenceId) &&
    ["INCIDENT", "INCIDENT_SIGNAL", "SERVICE_HEALTH", "ORDER_RECOVERY", "TRACE_SPAN"].includes(String(value.sourceType)) &&
    ["incident-service", "detection-store", "order-service", "tempo-via-gateway"].includes(String(value.sourceName)) &&
    isString(value.sourceId) && isNullableTimestamp(value.observedAt) &&
    (value.freshnessStatus === null || ["CURRENT", "PARTIAL", "STALE", "UNAVAILABLE"].includes(String(value.freshnessStatus))) &&
    isNullableString(value.signalCode) && isString(value.summary) && value.summary.length <= 280 && isRecord(value.details);
}

function isEvidenceGap(value: unknown): value is EvidenceGap {
  return isRecord(value) && ["SERVICE_HEALTH", "ORDER_RECOVERY", "TRACE"].includes(String(value.source)) &&
    isString(value.code) && isString(value.summary) && value.summary.length <= 240 && typeof value.required === "boolean";
}

function isSourceFreshness(value: unknown): value is SourceFreshness {
  return isRecord(value) && isString(value.source) &&
    ["CURRENT", "PARTIAL", "STALE", "UNAVAILABLE"].includes(String(value.status)) &&
    isTimestamp(value.attemptedAt) && isNullableTimestamp(value.lastSuccessAt) &&
    typeof value.itemCount === "number" && Number.isInteger(value.itemCount) && value.itemCount >= 0 &&
    isNullableString(value.errorCode);
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

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
