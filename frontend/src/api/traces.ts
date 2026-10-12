export type TraceSpan = {
  service: string;
  spanId: string;
  parentSpanId: string | null;
  name: string;
  startTime: string | null;
  endTime: string | null;
  status: "OK" | "ERROR" | "UNSET";
  httpMethod: string | null;
  httpRoute: string | null;
  httpStatusCode: number | null;
};

export type TraceSummary = {
  traceId: string;
  spans: TraceSpan[];
  truncated: boolean;
};

export class TraceApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "TraceApiError";
  }
}

export async function getTraceSummary(traceId: string, signal?: AbortSignal): Promise<TraceSummary> {
  if (!/^[0-9a-f]{32}$/.test(traceId)) throw new TraceApiError("This trace reference is not valid.");
  let response: Response;
  try {
    response = await fetch(`/api/v1/traces/${encodeURIComponent(traceId)}`, {
      signal,
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new TraceApiError("Tempo trace storage could not be reached.");
  }
  if (!response.ok) {
    if (response.status === 404) throw new TraceApiError("This trace is not available or has expired from local Tempo storage.", 404);
    if (response.status === 503) throw new TraceApiError("Tempo trace storage is unavailable; trace evidence could not be confirmed.", 503);
    throw new TraceApiError(`The trace API returned HTTP ${response.status}.`, response.status);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new TraceApiError("The trace API returned an unreadable response.", response.status);
  }
  if (!isTraceSummary(payload) || payload.traceId !== traceId) {
    throw new TraceApiError("The trace API returned data in an unexpected format.", response.status);
  }
  return payload;
}

function isTraceSummary(value: unknown): value is TraceSummary {
  return isRecord(value) &&
    isString(value.traceId) &&
    Array.isArray(value.spans) &&
    value.spans.length <= 250 &&
    value.spans.every(isTraceSpan) &&
    typeof value.truncated === "boolean";
}

function isTraceSpan(value: unknown): value is TraceSpan {
  return isRecord(value) &&
    isBoundedString(value.service, 64) &&
    isSpanId(value.spanId) &&
    (value.parentSpanId === null || isSpanId(value.parentSpanId)) &&
    isBoundedString(value.name, 120) &&
    isNullableTimestamp(value.startTime) &&
    isNullableTimestamp(value.endTime) &&
    (value.status === "OK" || value.status === "ERROR" || value.status === "UNSET") &&
    (value.httpMethod === null || ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].includes(String(value.httpMethod))) &&
    (value.httpRoute === null || (isBoundedString(value.httpRoute, 180) && value.httpRoute.startsWith("/"))) &&
    (value.httpStatusCode === null || isIntegerInRange(value.httpStatusCode, 100, 599));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isBoundedString(value: unknown, maximumLength: number): value is string {
  return isString(value) && value.length <= maximumLength;
}

function isSpanId(value: unknown): value is string {
  return isString(value) && /^[0-9a-f]{16}$/.test(value);
}

function isNullableTimestamp(value: unknown): value is string | null {
  return value === null || (isString(value) && Number.isFinite(Date.parse(value)));
}

function isIntegerInRange(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum && value <= maximum;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
