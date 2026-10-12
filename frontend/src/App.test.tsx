import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import App from "./App";

const detectionStatus = {
  status: "NOT_RUN",
  latestCycle: null,
  sources: [],
};

const incidentPage = {
  items: [],
  limit: 25,
  nextCursor: null,
  detectionStatus,
};

function jsonResponse(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TraceForge overview", () => {
  it("shows API health returned by the gateway", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/health") {
        return Promise.resolve(jsonResponse({
          status: "ok",
          service: "api-gateway",
          timestamp: "2026-10-10T10:30:00Z",
        }));
      }
      if (path === "/api/v1/detection-status") return Promise.resolve(jsonResponse(detectionStatus));
      return Promise.resolve(jsonResponse(incidentPage));
    }));

    render(<App />);

    expect(await screen.findByText(/api-gateway responding/i)).toBeInTheDocument();
  });

  it("explains when the real health API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection refused")));

    render(<App />);

    expect(await screen.findByText(/api unavailable/i)).toBeInTheDocument();
    expect(await screen.findByText(/incident results are unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/freshness could not be confirmed/i)).toBeInTheDocument();
  });
});
