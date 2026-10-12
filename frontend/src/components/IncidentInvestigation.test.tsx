import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { IncidentInvestigation } from "./IncidentInvestigation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const incidentId = "8eb4a00e-3c29-49a0-a8ad-452d7ef11001";
const evidenceId = "health-payment-service";

function report(overrides: Record<string, unknown> = {}) {
  return {
    investigationId: "9851ea45-c50d-455d-9203-c3387e8cda23",
    incidentId,
    generatedAt: "2026-10-12T10:00:00Z",
    status: "PARTIAL",
    provider: "deterministic-v1",
    summary: "Deterministic review collected 2 evidence items. 1 evidence gap is recorded.",
    uncertainty: "Some evidence is stale; this report does not establish root cause.",
    facts: [
      { claimId: "fact-health", text: "The latest persisted probe is DOWN.", evidenceIds: [evidenceId] },
    ],
    hypotheses: [],
    recommendedActions: [
      { claimId: "action-health", text: "Obtain fresh readiness observations.", evidenceIds: [evidenceId] },
    ],
    evidence: [
      {
        evidenceId,
        sourceType: "SERVICE_HEALTH",
        sourceName: "detection-store",
        sourceId: "payment-service",
        observedAt: "2026-10-12T09:59:00Z",
        freshnessStatus: "STALE",
        signalCode: "DOWN",
        summary: "Last persisted readiness result: DOWN.",
        details: { serviceName: "payment-service", probeStatus: "DOWN" },
      },
      {
        evidenceId: "incident",
        sourceType: "INCIDENT",
        sourceName: "incident-service",
        sourceId: incidentId,
        observedAt: "2026-10-12T09:59:00Z",
        freshnessStatus: "CURRENT",
        signalCode: null,
        summary: "Incident record: SERVICE_NOT_READY, OPEN.",
        details: { incidentStatus: "OPEN" },
      },
    ],
    evidenceGaps: [
      { source: "SERVICE_HEALTH", code: "HEALTH_SOURCE_NOT_CURRENT", summary: "The last service observation is stale.", required: true },
    ],
    sources: [
      { source: "payment-service", status: "STALE", attemptedAt: "2026-10-12T10:00:00Z", lastSuccessAt: "2026-10-12T09:59:00Z", itemCount: 1, errorCode: null },
    ],
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

describe("incident investigation panel", () => {
  it("distinguishes no saved result, runs against the API, and renders cited partial evidence", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") return jsonResponse(report());
      return jsonResponse({ detail: { code: "INVESTIGATION_NOT_FOUND" } }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<IncidentInvestigation incidentId={incidentId} />);

    expect(await screen.findByText("No investigation has been saved for this incident.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run investigation" }));

    expect(await screen.findByText("PARTIAL", { selector: ".status-badge" })).toBeInTheDocument();
    expect(screen.getByText("The latest persisted probe is DOWN.")).toBeInTheDocument();
    expect(screen.getByText("The last service observation is stale.")).toBeInTheDocument();
    expect(screen.getByText("payment-service")).toBeInTheDocument();
    const citations = screen.getAllByRole("link", { name: "SERVICE_HEALTH DOWN" });
    expect(citations).toHaveLength(2);
    expect(citations.every((link) => link.getAttribute("href") === `#investigation-evidence-${evidenceId}`)).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/incidents/${incidentId}/investigations/latest`, expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/incidents/${incidentId}/investigations`, expect.objectContaining({ method: "POST" }));
  });

  it("loads a saved result and does not present an API failure as an empty investigation", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(report()));
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(<IncidentInvestigation incidentId={incidentId} />);
    expect(await screen.findByText(/EVIDENCE-BASED REVIEW/i)).toBeInTheDocument();
    expect(screen.getByText("The latest persisted probe is DOWN.")).toBeInTheDocument();

    fetchMock.mockImplementationOnce(async () => jsonResponse({ detail: { code: "DETECTION_STORE_UNAVAILABLE" } }, 503));
    rerender(<IncidentInvestigation incidentId={`${incidentId}-next`} />);
    expect(await screen.findByText("Investigation data is unavailable.")).toBeInTheDocument();
    expect(screen.getByText(/does not mean the incident is resolved/)).toBeInTheDocument();
    expect(screen.queryByText("No investigation has been saved for this incident.")).not.toBeInTheDocument();
  });

  it("rejects a report with a citation outside the collected evidence", async () => {
    const malformed = report({
      facts: [{ claimId: "unsupported", text: "Unsupported claim", evidenceIds: ["not-collected"] }],
    });
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(malformed)));
    render(<IncidentInvestigation incidentId={incidentId} />);

    expect(await screen.findByText("Investigation data is unavailable.")).toBeInTheDocument();
    expect(screen.getByText("The investigation API returned data in an unexpected format.")).toBeInTheDocument();
  });
});
