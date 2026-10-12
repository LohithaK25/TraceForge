# ADR 0006: Deterministic incident detection boundaries

- **Status:** Accepted; backend detection, persistence, and read APIs implemented and locally verified (2026-10-10). The frontend incident and freshness views passed local tests/build, Vite-proxy checks, and desktop browser verification on 2026-10-12; mobile/exhaustive browser coverage and remote CI remain unverified.
- **Date:** 2026-10-10

## Context

TraceForge has durable order recovery state, private Spring Actuator readiness endpoints, and a local traces-only Collector → Tempo pipeline. Tempo export is asynchronous and best-effort, so a healthy trace backend does not prove that every workflow has queryable traces. Order, Inventory, and Payment own separate schemas and their data must not be joined directly by a detector. Phase 4 adds an internal FastAPI service, bounded source clients, deterministic rules, scheduled evaluation, PostgreSQL incident/freshness storage, and gateway-proxied incident reads.

## Decision

The separate investigation service owns service health probing, observation freshness, deterministic rule evaluation, incident persistence/deduplication, and future incident read APIs. Implemented code resides in the internal `investigation-service` Compose container and stores incident episodes and health streak state in the dedicated `incident_service` PostgreSQL schema. It obtains recovery observations through the bounded Order Service endpoint and does not read or write Order, Inventory, or Payment tables. The existing PostgreSQL service is sufficient for the local incident store; no additional database or workflow engine is required. Schema ownership is logical only while services share one local database user.

The two initial rules are:

1. **`SERVICE_NOT_READY`** opens after two consecutive failed, timed-out, or non-`UP` readiness probes for the same service and resolves after two consecutive `UP` probes.
2. **`ORDER_RECOVERY_STALLED`** identifies overdue active recovery work or incomplete required compensation. It resolves only after the order is terminal and required compensation is complete.

Confirmed orders and ordinary business rejections are not incidents. In particular, `FAILED` with `PAYMENT_DECLINED` and `inventoryReleased=true` is a completed business outcome, not incomplete compensation. Health and persisted recovery state are detection inputs. Tempo is optional evidence enrichment; missing, stale, disabled, or unavailable telemetry must not be interpreted as a healthy state or as proof that no incident exists.

The incident lifecycle is `OPEN` → `RESOLVED`. Repeated observations are deduplicated by stable rule/source fingerprint and update the open episode. A recurrence after resolution can create a new episode. Detection freshness is reported separately as current, partial, or stale; failed source queries do not resolve incidents.

Stage 1 adds `GET /internal/v1/orders/attention`. It returns active orders with a recovery error, incomplete compensation, or a due recovery time. Paging defaults to 50 items and is capped at 100. It orders by `(created_at, id)` and accepts both `afterCreatedAt` and `afterId` as a keyset cursor. Response items expose only the order ID, workflow status, fixed failure/recovery codes, attempt count, next recovery timestamp, inventory-release state, created/updated timestamps, and nullable originating trace ID. No SKU, quantity, payment amount or identifier, request body, headers, credentials, or free-form exception data is returned. The Order Service port is private to the Compose network and this endpoint is not proxied by the gateway.

The Investigation Service runs a configurable single-cycle-at-a-time scheduler. A PostgreSQL advisory lock prevents simultaneous evaluation by multiple replicas. It persists health streaks, incidents, detection-cycle outcomes, and per-source freshness in `incident_service`; the shared local database role means this schema boundary is logical, not an authorization boundary. Its health and Order clients use fixed destinations, timeouts, body/page/count limits, and strict response models. Partial or failed collection is kept distinct from an empty healthy result.

The Order Service provides a bounded active recovery feed and `GET /internal/v1/orders/recovery-observations?orderIds=...` for up to 100 unique order IDs already attached to open recovery incidents. The latter reports explicit found terminal state and `missingOrderIds`; missing rows are not interpreted as success. The detector resolves an order incident only on an explicit terminal `CONFIRMED` or `FAILED` observation with required compensation complete. Source failures and stale observations cannot resolve incidents.

The Investigation Service exposes health/readiness internally and bounded `/api/v1/incidents`, `/api/v1/incidents/{id}`, and `/api/v1/detection-status` routes through the Gateway. List requests accept only `OPEN` or `RESOLVED`, cap the page at 100, and use an opaque cursor. Detection status reports the latest persisted cycle and source status separately from incident state. The React dashboard consumes these routes for open incidents, resolved history, selected incident evidence, and per-source freshness; empty findings and unavailable/stale data remain distinct. The 2026-10-12 frontend tests/build and Vite-proxy HTTP checks passed. Desktop browser verification covered the empty open state, current freshness, resolved history, and real incident detail; mobile/exhaustive browser coverage and remote CI remain unverified. Tempo remains optional evidence and is not queried by rules. `scripts/test-investigation.ps1` uses disposable tmpfs PostgreSQL; the pinned Java and live Compose verification commands and results are recorded in `TASKS.md`.

## Consequences

- Once invoked, detection can work when traces are missing or Tempo is unavailable; the current engine does not query Tempo and trace references remain optional supporting evidence.
- The order query reflects persisted current state, not a complete event history. Short-lived states can be missed, and historical error-rate or latency rules require a future durable event/metrics source.
- Local backend detection, incident persistence/deduplication, freshness, and read APIs are implemented and verified. The dashboard's incident and freshness views are implemented with local frontend and desktop browser checks; mobile/exhaustive browser coverage, remote CI, and production authorization/database roles remain unverified.
- The detector observes current persisted state rather than a complete event history. Brief states can be missed, and historical rate/latency rules need a separate durable signal source. No resolution is inferred from a missing Order row or failed/stale source.
- The Compose demo's internal service network is a local boundary, not production authentication or authorization. Do not publish the Order Service port or route this endpoint through the gateway without a separate security decision.

## Alternatives not selected

- **Use Tempo as the detector's primary signal:** rejected because trace export is asynchronous, best-effort, retained locally for a bounded period, and no general detector query contract exists.
- **Read business tables directly:** rejected because it bypasses service ownership and couples the detector to Order's schema.
- **Add Prometheus or a broker in this increment:** deferred; neither is required for the two initial rules and both add operational scope.
