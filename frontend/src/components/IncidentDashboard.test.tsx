import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import { IncidentDashboard } from "./IncidentDashboard";
import type { DetectionStatusResponse, IncidentPage, IncidentRecord } from "../api/incidents";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const incidentId = "8eb4a00e-3c29-49a0-a8ad-452d7ef11001";
const firstSeenAt = "2026-10-10T12:00:00Z";
const secondSeenAt = "2026-10-10T12:00:05Z";

function sourceStatus(overrides: Partial<DetectionStatusResponse> = {}): DetectionStatusResponse {
  return {
    status: "CURRENT",
    latestCycle: {
      cycleId: "d0b46ef7-dbb2-4dab-a1c2-19cd5f61d001",
      startedAt: firstSeenAt,
      completedAt: secondSeenAt,
      status: "COMPLETE",
      findingsOpenedOrUpdated: 0,
      incidentsResolved: 0,
      failureCode: null,
    },
    sources: [
      {
        source: "api-gateway",
        status: "CURRENT",
        attemptedAt: secondSeenAt,
        lastSuccessAt: secondSeenAt,
        itemCount: 1,
        errorCode: null,
      },
      {
        source: "order-attention",
        status: "CURRENT",
        attemptedAt: secondSeenAt,
        lastSuccessAt: secondSeenAt,
        itemCount: 0,
        errorCode: null,
      },
    ],
    services: [
      "api-gateway", "order-service", "inventory-service", "payment-service",
    ].map((serviceName) => ({
      serviceName: serviceName as "api-gateway" | "order-service" | "inventory-service" | "payment-service",
      status: "UP" as const,
      observedAt: secondSeenAt,
      freshnessStatus: "CURRENT" as const,
      incidentOpen: false,
    })),
    ...overrides,
  };
}

function incident(overrides: Partial<IncidentRecord> = {}): IncidentRecord {
  return {
    id: incidentId,
    ruleKey: "ORDER_RECOVERY_STALLED",
    ruleVersion: 1,
    severity: "HIGH",
    status: "OPEN",
    fingerprint: "a".repeat(64),
    scopeType: "ORDER",
    sourceReference: "ab3163ab-2240-4578-b012-9b8f9226b7f2",
    firstSeenAt,
    lastSeenAt: secondSeenAt,
    lastEvaluatedAt: secondSeenAt,
    resolvedAt: null,
    occurrenceCount: 2,
    summary: "Order compensation is still required",
    evidence: [
      {
        sourceType: "ORDER_RECOVERY",
        sourceId: "ab3163ab-2240-4578-b012-9b8f9226b7f2",
        observedAt: secondSeenAt,
        signalCode: "COMPENSATION_REQUIRED",
        traceId: null,
      },
    ],
    originTraceId: null,
    createdAt: firstSeenAt,
    updatedAt: secondSeenAt,
    ...overrides,
  };
}

function page(
  items: IncidentRecord[] = [],
  nextCursor: string | null = null,
  detectionStatus: DetectionStatusResponse = sourceStatus(),
): IncidentPage {
  return { items, limit: 25, nextCursor, detectionStatus };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

function installApi(
  options: {
    openPage?: IncidentPage;
    resolvedPage?: IncidentPage;
    freshness?: DetectionStatusResponse;
    detail?: IncidentRecord;
    trace?: unknown;
    traceStatus?: number;
    listStatus?: number;
  } = {},
) {
  const requests: string[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    requests.push(path);
    if (path === "/api/v1/detection-status") return jsonResponse(options.freshness ?? sourceStatus());
    if (path === `/api/v1/incidents/${incidentId}`) return jsonResponse(options.detail ?? incident());
    if (path === `/api/v1/traces/${"b".repeat(32)}`) return jsonResponse(options.trace ?? {}, options.traceStatus ?? 200);
    if (path.includes("status=RESOLVED")) return jsonResponse(options.resolvedPage ?? page());
    if (options.listStatus && options.listStatus !== 200) return jsonResponse({}, options.listStatus);
    return jsonResponse(options.openPage ?? page());
  });
  vi.stubGlobal("fetch", fetchMock);
  return { requests, fetchMock };
}

describe("incident dashboard", () => {
  it("loads real open incidents, source freshness, and selected incident detail", async () => {
    const { requests } = installApi({ openPage: page([incident()]) });
    render(<IncidentDashboard />);

    expect(await screen.findByText("Order compensation is still required")).toBeInTheDocument();
    expect(screen.getByText("Detection-source freshness")).toBeInTheDocument();
    expect(screen.getByText("Service health")).toBeInTheDocument();
    expect(screen.getAllByText("api-gateway")).toHaveLength(2);
    expect(screen.getByText("order-attention")).toBeInTheDocument();
    expect(screen.getByText("The latest detection cycle and its sources are within the reported freshness window.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View details" }));
    expect(await screen.findByText(incidentId)).toBeInTheDocument();
    expect(screen.getByText("COMPENSATION_REQUIRED")).toBeInTheDocument();
    expect(requests).toContain(`/api/v1/incidents/${incidentId}`);
  });

  it("shows an empty result separately from stale and unavailable sources", async () => {
    const services = sourceStatus().services.map((service) => service.serviceName === "payment-service"
      ? { ...service, status: "DOWN" as const, freshnessStatus: "STALE" as const }
      : service);
    const stale = sourceStatus({
      status: "STALE",
      services,
      sources: [
        {
          source: "payment-service",
          status: "UNAVAILABLE",
          attemptedAt: secondSeenAt,
          lastSuccessAt: firstSeenAt,
          itemCount: 0,
          errorCode: "UPSTREAM_UNAVAILABLE",
        },
      ],
    });
    installApi({ openPage: page([], null, stale), freshness: stale });
    render(<IncidentDashboard />);

    expect(await screen.findByText("No open incidents were returned.")).toBeInTheDocument();
    expect(screen.getByText("The last successful observations are stale; current service health is not confirmed.")).toBeInTheDocument();
    expect(screen.getByText("UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("UPSTREAM_UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("Current readiness is not confirmed.")).toBeInTheDocument();
  });

  it("loads resolved history through the supported status filter", async () => {
    const resolved = incident({
      ruleKey: "SERVICE_NOT_READY",
      scopeType: "SERVICE",
      sourceReference: "inventory-service",
      status: "RESOLVED",
      resolvedAt: secondSeenAt,
      summary: "Inventory service was not ready",
    });
    const { requests } = installApi({ resolvedPage: page([resolved]) });
    render(<IncidentDashboard />);

    fireEvent.click(screen.getByRole("button", { name: "Resolved history" }));

    expect(await screen.findByText("Inventory service was not ready")).toBeInTheDocument();
    expect(screen.getByText("Service not ready")).toBeInTheDocument();
    expect(requests.some((request) => request.includes("status=RESOLVED"))).toBe(true);
  });

  it("passes the opaque next cursor unchanged and appends the next page", async () => {
    const cursor = "cursor_opaque-123";
    const secondIncident = incident({
      id: "8eb4a00e-3c29-49a0-a8ad-452d7ef11002",
      summary: "Another recovery case",
      sourceReference: "f391aeb7-fac5-4613-9c21-878ab169f997",
    });
    const { requests, fetchMock } = installApi({ openPage: page([incident()], cursor) });
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input);
      requests.push(path);
      if (path === "/api/v1/detection-status") return jsonResponse(sourceStatus());
      if (path.includes(`cursor=${cursor}`)) return jsonResponse(page([secondIncident]));
      if (path.includes("status=RESOLVED")) return jsonResponse(page());
      return jsonResponse(page([incident()], cursor));
    });
    render(<IncidentDashboard />);

    expect(await screen.findByText("Order compensation is still required")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Another recovery case")).toBeInTheDocument();
    expect(requests.some((request) => request.includes(`cursor=${cursor}`))).toBe(true);
  });

  it("keeps loading visible until the incident response arrives", async () => {
    let resolvePage!: (response: Response) => void;
    const delayedPage = new Promise<Response>((resolve) => { resolvePage = resolve; });
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/incidents?status=OPEN&limit=25") return delayedPage;
      if (path === "/api/v1/detection-status") return Promise.resolve(jsonResponse(sourceStatus()));
      return Promise.resolve(jsonResponse(page()));
    }));
    render(<IncidentDashboard />);

    expect(screen.getByText(/Loading open incidents/i)).toBeInTheDocument();
    await act(async () => resolvePage(jsonResponse(page())));
    expect(await screen.findByText("No open incidents were returned.")).toBeInTheDocument();
  });

  it("does not turn an API failure into an empty or healthy state", async () => {
    const unavailable = sourceStatus({ status: "UNAVAILABLE", sources: [] });
    installApi({ listStatus: 503, freshness: unavailable });
    render(<IncidentDashboard />);

    expect(await screen.findByText("Incident results are unavailable.")).toBeInTheDocument();
    expect(screen.getByText("An API error is not an empty incident list.")).toBeInTheDocument();
    expect(screen.getByText("Detection status is unavailable; service health is not confirmed.")).toBeInTheDocument();
    expect(screen.queryByText("No open incidents were returned.")).not.toBeInTheDocument();
  });

  it("shows a detail API error without hiding the incident list", async () => {
    const { fetchMock } = installApi({ openPage: page([incident()]) });
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === `/api/v1/incidents/${incidentId}`) return jsonResponse({}, 404);
      if (path === "/api/v1/detection-status") return jsonResponse(sourceStatus());
      return jsonResponse(page([incident()]));
    });
    render(<IncidentDashboard />);

    expect(await screen.findByText("Order compensation is still required")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This incident is no longer available.");
    expect(screen.getByText("Order compensation is still required")).toBeInTheDocument();
  });

  it("loads a trace only on request and renders the bounded span summary", async () => {
    const traceId = "b".repeat(32);
    const detail = incident({ originTraceId: traceId });
    const { requests } = installApi({
      openPage: page([detail]),
      detail,
      trace: {
        traceId,
        truncated: false,
        spans: [
          {
            service: "api-gateway", spanId: "0123456789abcdef", parentSpanId: null,
            name: "GET /api/v1/orders/{id}", startTime: firstSeenAt, endTime: secondSeenAt,
            status: "OK", httpMethod: "GET", httpRoute: "/api/v1/orders/{id}", httpStatusCode: 200,
          },
        ],
      },
    });
    render(<IncidentDashboard />);

    fireEvent.click(await screen.findByRole("button", { name: "View details" }));
    expect(await screen.findByText("Trace evidence from Tempo")).toBeInTheDocument();
    expect(requests.some((path) => path.startsWith("/api/v1/traces/"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Load trace" }));

    expect(await screen.findByText("GET /api/v1/orders/{id}")).toBeInTheDocument();
    expect(screen.getByText("1 spans from api-gateway")).toBeInTheDocument();
    expect(requests).toContain(`/api/v1/traces/${traceId}`);
  });

  it("shows unavailable Tempo evidence without treating it as an empty trace", async () => {
    const traceId = "b".repeat(32);
    const detail = incident({ originTraceId: traceId });
    installApi({ openPage: page([detail]), detail, traceStatus: 503 });
    render(<IncidentDashboard />);

    fireEvent.click(await screen.findByRole("button", { name: "View details" }));
    fireEvent.click(await screen.findByRole("button", { name: "Load trace" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Tempo trace storage is unavailable; trace evidence could not be confirmed.");
  });
});
