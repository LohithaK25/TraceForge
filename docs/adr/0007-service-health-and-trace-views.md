# ADR 0007: Service health and trace evidence views

- **Status:** Implemented and locally backend-verified on 2026-10-12; selected desktop dashboard states manually documented by four supplied screenshots. Mobile/exhaustive browser coverage and remote CI remain unverified.
- **Date:** 2026-10-12

## Context

Phase 4 already persists the last readiness probe per service and exposes detection-source freshness. It also returns optional trace IDs on incident evidence. The dashboard had no view of the persisted per-service probe outcome and no supported Gateway route for reading Tempo. Direct browser access to Tempo would bypass the existing Gateway boundary and expose Tempo's raw response contract to the frontend.

## Decision

Extend `GET /api/v1/detection-status` with a fixed four-entry `services` array for `api-gateway`, `order-service`, `inventory-service`, and `payment-service`. Each entry contains the last observed `UP`, `DOWN`, `TIMEOUT`, or `UNKNOWN` probe status; nullable observation timestamp; collection freshness; and whether a `SERVICE_NOT_READY` incident is open. No health result is inferred when there has been no observation: it is reported as `UNKNOWN`, with no timestamp and `UNAVAILABLE` freshness. Staleness is calculated from the same persisted source freshness state as the existing detection status.

Add `GET /api/v1/traces/{traceId}` at the Gateway. It accepts exactly 32 lowercase hexadecimal characters, calls Tempo's fixed `/api/v2/traces/{traceId}` route, and uses bounded connect/read timeouts. The upstream response is limited to 1 MiB and at most 250 returned spans. The Gateway maps Tempo's OTLP JSON variants into `traceId`, `spans`, and `truncated`. Each span exposes only service name, span/parent IDs, bounded operation name, start/end timestamps, normalized status, and allowlisted HTTP method/route/status. Raw attributes, events, exception messages, request/response bodies, payment data, and unknown fields are discarded. Missing trace data returns 404; Tempo/network unavailability returns 503; malformed or oversized responses return a safe 502. The frontend loads trace summaries only on explicit user action and never calls Tempo directly.

The trace reader uses the Jackson 3 `JsonMapper` provided by the existing Spring Boot 4.1.1 web stack; it adds no separate JSON library or Jackson 2 compatibility dependency.

These read APIs do not alter incident detection, source freshness, incident lifecycle, or business outcomes. Trace availability is optional supporting evidence. This is still a local unauthenticated demo boundary, not production access control.

## Consequences

- Operators can distinguish a persisted last probe result from its age/freshness and the deterministic incident state.
- The dashboard can inspect trace service participation and HTTP outcomes without receiving arbitrary Tempo attributes.
- A successful empty incident list, unavailable trace, or stale last health observation is not presented as proof of health or resolution.
- The Investigation Service suite passed 54 tests and the pinned Gateway suite passed 8 tests. Live detection verification passed against the rebuilt services. A caller-supplied trace ID was queried through the Gateway and returned four sanitized spans from Gateway and Inventory; malformed and missing IDs returned 400 and 404, and an unavailable Tempo returned 503 before being restored healthy. The response stayed within the 1 MiB / 250-span bounds.

## Verification expectations

- Investigation tests cover no observations, a known `DOWN` result, open incident state, freshness, and stale observations.
- Gateway tests cover valid/invalid IDs, modern and legacy Tempo JSON, status/trace-ID filtering, allowlisted fields, missing/unavailable traces, and response/span bounds.
- Frontend tests cover service status/freshness presentation, explicit trace loading, bounded span rendering, and unavailable trace evidence.
- Four supplied screenshots manually document the selected desktop dashboard states: service probes/freshness, detection-source freshness, honest empty-open state, resolved history, a detail with real `HEALTH_PROBE` / `CONNECT_FAILED` evidence, and trace evidence when no trace references are returned. This is limited visual evidence, not exhaustive interaction, network-request, or mobile verification. An earlier browser-automation attempt rejected the local URL under its security policy. Remote CI, production authorization, and separate database-role enforcement remain unverified.
