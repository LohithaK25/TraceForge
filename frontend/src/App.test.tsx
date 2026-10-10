import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TraceForge overview", () => {
  it("shows API health returned by the gateway", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: "ok",
          service: "api-gateway",
          timestamp: "2026-10-10T10:30:00Z",
        }),
      }),
    );

    render(<App />);

    expect(await screen.findByText(/api-gateway responding/i)).toBeInTheDocument();
  });

  it("explains when the real health API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection refused")));

    render(<App />);

    expect(await screen.findByText(/api unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/no sample telemetry is being shown/i)).toBeInTheDocument();
  });
});
