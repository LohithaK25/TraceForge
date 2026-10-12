# TraceForge

TraceForge is an evidence-first distributed incident investigation project. Its runnable sample application demonstrates a durable order → inventory reservation → payment authorization saga. The dashboard shows gateway health, API-backed incidents, persisted service-health observations, detection-source freshness, and on-demand trace summaries; it does not invent orders, payments, incidents, traces, metrics, or investigation results.

## Current implementation

- API Gateway, Order Service, Inventory Service, Payment Service, and PostgreSQL run in Docker Compose.
- Orders, reservations, and payment attempts use separate PostgreSQL schemas and Flyway migrations on the persistent `traceforge-postgres-data` volume.
- Order creation uses a required client idempotency key. Inventory reservation, inventory release, and payment authorization are each idempotent at their service boundary.
- A persisted recovery worker resumes uncertain operations and compensation. See [docs/architecture.md](docs/architecture.md) for the state machine and consistency limits.
- All four Java services use the same pinned OpenTelemetry Java agent. The local Collector exports traces to Tempo, which Grafana Explore can query. The Gateway returns a bounded, sanitized trace summary only when the user explicitly loads an API-supplied trace reference.
- The Python/FastAPI investigation service runs scheduled deterministic health and recovery detection, persists incidents, service probe state, and source freshness in the `incident_service` schema, and exposes bounded read APIs through the gateway. The dashboard lists incidents and resolved history, separates last service probe results from freshness, and loads real trace summaries on demand.
- The payment provider is a deterministic local simulator. No real payment rail, card number, or other payment credential is accepted or processed.

For the complete local startup, demo, verification, and troubleshooting workflow, see the [developer runbook](docs/runbook.md).

## Prerequisites

- Docker Desktop with Linux containers enabled.
- Node.js 22.12 or later and npm to run the dashboard.
- A local Java 21 JDK and Maven are optional. Backend builds and tests use the pinned `maven:3.9.16-eclipse-temurin-21` image; service images run on `eclipse-temurin:21-jre-alpine`.

PostgreSQL credentials in `.env.example` are local-development placeholders. Do not reuse them outside the local demo.

## Run locally

From the repository root:

```powershell
docker compose up --build -d --wait
```

On this Windows development host, the configured `default` Docker context (`npipe:////./pipe/docker_engine`) returned permission denied while the `desktop-linux` context was available. To use the working Docker Desktop endpoint for the current PowerShell session without changing persistent context settings, run `$env:DOCKER_CONTEXT = 'desktop-linux'` before Compose commands, or use `docker --context desktop-linux ...` for individual commands.

The gateway is published on `127.0.0.1:8080`, Tempo's query API on `127.0.0.1:3200`, and Grafana on `127.0.0.1:3000`. Order, Inventory, Payment, PostgreSQL, the Collector receiver, and Investigation Service have no host-published ports. Compose enables the `local` Spring profile for this demo, which gates the deterministic failure controls and manual recovery endpoint. Open Grafana at `http://localhost:3000` and choose Explore → Tempo. Local default credentials are `admin` / `traceforge-local-only`; override them in an ignored `.env` file before use if needed.

To run the dashboard in another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open the Vite URL printed by the command. The overview checks `GET /api/v1/health` and reads `GET /api/v1/incidents?status=OPEN&limit=25` plus `GET /api/v1/detection-status` through the Vite proxy. The resolved-history filter uses the same incident-list endpoint with `status=RESOLVED`; selecting an item reads `GET /api/v1/incidents/{id}`. Empty incident results and detection-source freshness are shown separately, so an empty list or stale source is not presented as proof of health.

## Order API

Create an order through the gateway. `Idempotency-Key` is required and must be reused for an exact retry of the same payload.

```http
POST http://localhost:8080/api/v1/orders
Content-Type: application/json
Idempotency-Key: demo-order-001

{"sku":"SKU-ALPHA","quantity":2}
```

An initial success returns HTTP 201 with `status: "CONFIRMED"`, an inventory reservation ID, and a payment authorization ID. Each demo unit is assigned 100 synthetic minor units for the simulator; this value is not a product price or a real charge. Read the stored result with `GET /api/v1/orders/{id}`.

Repeating the same key and payload returns the original order without starting new side effects. Reusing its key with a different SKU or quantity returns HTTP 409. Input validation requires SKU syntax `[A-Z0-9][A-Z0-9-]{0,31}` and quantity 1–1000; invalid requests return HTTP 400 before insertion.

| Outcome | Order state | HTTP result |
| --- | --- | --- |
| Inventory reserved and payment authorized | `CONFIRMED` | 201 |
| Unknown SKU | `FAILED` / `UNKNOWN_SKU` | 404 |
| Insufficient stock | `FAILED` / `INSUFFICIENT_STOCK` | 409 |
| Payment declined and inventory release completed | `FAILED` / `PAYMENT_DECLINED`, `inventoryReleased: true` | 402 |
| Inventory/payment outcome uncertain or dependency unavailable | `PENDING` or `INVENTORY_RESERVED` | 503 |
| Payment decline awaiting inventory release | `COMPENSATION_REQUIRED` | 503 |

## Internal service APIs

Payment Service accepts `POST /internal/v1/payments/authorizations` with `Idempotency-Key` and a validated `{ "orderId": "…", "amountMinor": 200 }` body. It returns a persisted `AUTHORIZED` or `DECLINED` result. Repeating the key and same details returns that row; a changed order or amount returns 409. Inventory Service releases a hold through `POST /internal/v1/inventory/reservations/{orderId}/release`. Both internal services are reachable only on the Compose network.

## Local recovery and controlled failures

`POST /api/v1/orders/{id}/recover` asks Order Service to make one idempotent recovery attempt. It is enabled only in the `local` profile. A scheduled worker also scans persisted recoverable orders every five seconds; each retry is delayed at least 15 seconds and automatic retries stop after ten failed attempts. An exhausted order remains visible with `recoveryError: "AUTOMATIC_RETRIES_EXHAUSTED"` and can be manually retried in the local profile.

Use the optional `X-TraceForge-Failure` header on a create request to reproduce a controlled path:

| Header value | Expected persisted behavior |
| --- | --- |
| `inventory-unavailable` | Inventory fails before mutation; order stays `PENDING`. |
| `inventory-timeout-after-commit` | Reservation commits, response is delayed past the Order Service timeout; recovery finds the same reservation and does not decrement twice. |
| `payment-decline` | Declined payment is persisted; Inventory releases the reservation; order becomes `FAILED`. |
| `payment-unavailable` | No payment attempt is persisted; order stays `INVENTORY_RESERVED` and can be retried. |
| `payment-timeout-after-commit` | Authorization persists before the response timeout; retry returns the same authorization. |
| `payment-decline-compensation-unavailable` | Decline persists, release fails before mutation, order remains `COMPENSATION_REQUIRED`; recovery later releases stock. |

All injected scenarios are rejected outside the explicit `local` profile. They do not accept or log sensitive payment data. The local profile is for development only.

## Distributed traces

Every service image includes the pinned OpenTelemetry Java agent. Incoming HTTP server spans, outgoing HTTP client spans, and the W3C `traceparent` context are created/propagated by the agent. Business spans add order outcomes, local failure codes, order IDs, and reservation/payment operation IDs. The Collector accepts OTLP/HTTP protobuf inside Compose and exports traces to Tempo over OTLP/gRPC. Tempo's local storage uses the persistent `traceforge-tempo-data` volume and retains completed blocks for 24 hours.

The agent and custom spans do not capture payment details, request/response bodies, or HTTP headers. Custom exceptions record the exception type without the free-form message. Baggage propagation is disabled. Order IDs and operation IDs appear only as trace attributes, never as metric labels; metric and log exporters are disabled for this milestone. See [docs/security.md](docs/security.md) for the local-only exposure and retention assumptions.

The pinned upstream Tempo and Collector binaries run in small Alpine wrappers so Compose can make real HTTP readiness checks; the upstream images do not include a shell or `wget`. Their ingestion and health endpoints remain private to the Compose network.

Run the real trace check from PowerShell:

```powershell
.\scripts\verify-traces.ps1
```

It sends orders with unique, known `traceparent` values, calls the Tempo trace-by-ID API, and polls until traces contain the expected services/spans or a bounded timeout expires. It verifies a confirmed order, unknown-SKU rejection, payment decline plus inventory release, and a payment-service outage followed by a scheduled recovery span linked to the originating order span. It also temporarily stops the local Collector to check that a payment decline and inventory compensation retain their business result during telemetry loss; the script restores the Collector before it exits. It prints trace IDs that can be used in Grafana Explore. The controlled scenarios create local test data and consume inventory for successful/outage-recovered orders.

Query a trace directly after the script prints its trace ID:

```powershell
$traceId = 'paste-32-hex-character-trace-id-here'
Invoke-RestMethod "http://localhost:3200/api/v2/traces/$traceId"
```

The order service stores the originating trace/span IDs in private PostgreSQL columns for restart-safe recovery links; these fields are not part of the order API response. A scheduled recovery is a new trace with a span link, not a child of a completed HTTP span. Setting `TRACEFORGE_TRACING_ENABLED=false` in `.env` disables the Java agent while leaving the business services running. Traces remain queryable until Tempo's configured retention removes their blocks; `docker compose down -v` deletes the trace volume along with the database volume.

If spans do not appear, check `docker compose ps`, then `docker compose logs otel-collector tempo`. The script polls Tempo for up to 45 seconds per immediate trace and uses a bounded wait for the recovery link; a healthy Collector alone is not proof that spans were stored.

## Incident detection APIs

The investigation service probes fixed service readiness endpoints and reads bounded Order recovery state. It does not query Tempo to decide incidents. `SERVICE_NOT_READY` opens after two consecutive failed or timed-out probes and resolves after two consecutive `UP` probes. `ORDER_RECOVERY_STALLED` covers overdue recovery and incomplete compensation; it resolves only after Order explicitly reports a terminal state with required compensation complete. Confirmed orders and fully compensated payment declines are ordinary outcomes, not incidents. Failed or stale sources do not resolve incidents; source freshness is exposed separately.

The investigation service has no host-published port. Use the gateway's read-only routes:

```powershell
Invoke-RestMethod 'http://localhost:8080/api/v1/incidents?status=OPEN&limit=50'
Invoke-RestMethod 'http://localhost:8080/api/v1/detection-status'
Invoke-RestMethod 'http://localhost:8080/api/v1/incidents/{incident-id}'
```

Incident listing supports `OPEN` or `RESOLVED`, an optional opaque cursor, and a strict 1–100 item limit. The detection-status response includes the latest persisted cycle and per-source freshness. Reproduce the live synthetic scenarios with `scripts/verify-detection.ps1`; `scripts/test-backend.ps1` runs it after backend and Tempo checks. This script temporarily stops Order, Inventory, and the optional Collector for controlled checks, restores them in `finally`, and cleans its run-scoped business rows and order incidents. Resolved service-health incidents from the simulated outages remain as incident history.

The dashboard consumes these read-only contracts through the gateway. Its incident list is paginated with an opaque cursor, resolved history is available through the status filter, and each selected incident can load bounded evidence details. Detection freshness is independent of incident state; unavailable, stale, partial, or not-yet-run sources are described as unconfirmed rather than healthy.

## Service health and trace evidence

The dashboard shows the last persisted readiness result for the API Gateway, Order, Inventory, and Payment services from `GET /api/v1/detection-status`. Each service row includes `UP`, `DOWN`, `TIMEOUT`, or `UNKNOWN`, the observation time, collection freshness, and whether a service-not-ready incident is open. These are the latest collected observations, not synchronous probes initiated by the browser. Missing observations are `UNKNOWN`/`UNAVAILABLE`; a stale last `UP` result is not represented as current health.

For incident trace references, select **Load trace** to call `GET /api/v1/traces/{traceId}` on the Gateway. The Gateway queries Tempo's fixed trace-by-ID endpoint and returns only a summary of at most 250 spans from a response capped at 1 MiB. The summary contains service and span identifiers, operation names, times, span status, and allowlisted HTTP method, route, and status code. Raw Tempo attributes and events are not exposed. A missing trace (404) and an unavailable Tempo backend (503) are shown as unavailable evidence, not as an empty or resolved incident. The frontend never queries Tempo directly.

The incident list/detail, detection status, and trace summary are read-only local-demo APIs. Phase 5 backend tests and local runtime checks passed on 2026-10-12: 54 Investigation tests, 8 Gateway tests, live detection/recovery checks, and bounded trace queries through the rebuilt Gateway. Four supplied desktop screenshots document selected dashboard states, not every interaction or network request. Remote CI, production authorization, and separate database-role enforcement remain unverified. See [TASKS.md](TASKS.md) and [ADR 0007](docs/adr/0007-service-health-and-trace-views.md).

## Evidence-backed investigations

Open an incident's details and select **Run investigation** to request a real evidence collection. The dashboard first loads the persisted latest result, if one exists. `GET /api/v1/incidents/{id}/investigations/latest` returns that result or `404` with `INVESTIGATION_NOT_FOUND`; `POST /api/v1/incidents/{id}/investigations` performs a bounded collection, validates citations, and persists the latest snapshot. Both routes go through the Gateway; the Investigation Service has no host-published port. A report only updates its own row in `incident_service`; it does not create, resolve, or update an incident or business workflow.

```powershell
$incidentId = '<incident UUID returned by the incident API>'
$investigation = Invoke-RestMethod -Uri "http://localhost:8080/api/v1/incidents/$incidentId/investigations" -Method Post
$investigation | Select-Object status, provider, summary, uncertainty
Invoke-RestMethod -Uri "http://localhost:8080/api/v1/incidents/$incidentId/investigations/latest"
```

The versioned result separates `facts`, qualified `hypotheses`, `recommendedActions`, `evidence`, `evidenceGaps`, per-run `sources`, and a human-readable `uncertainty` statement. Every claim carries evidence IDs and the service rejects citations outside the collected evidence. `COMPLETE` means required owning-service evidence was current when collected; it is not proof of root cause. `PARTIAL` identifies stale, missing, contradictory, or unavailable referenced evidence. `INSUFFICIENT` means required evidence could not be confirmed. A missing optional trace reference is shown as a gap without changing deterministic incident status.

Evidence is allowlisted and provenance-bearing: persisted incident/rule fields, the current persisted service probe snapshot, explicit Order recovery observations, and sanitized trace spans queried by trace ID through the Gateway. Trace collection is limited to 3 references, at most 20 spans per trace, and a 1 MiB Gateway response; the report is capped at 100 evidence items and stored JSON is capped at 256 KiB. Raw request bodies/headers, payment values or credentials, raw exceptions, and Tempo attributes/events are not included. The API uses the fixed deterministic `deterministic-v1` provider; `.env.example` has no provider credentials/model configured, so no external LLM is called. Provider configuration alone does not enable one.

The Investigation Service applies migration `0003_incident_investigations.sql` and stores one latest result per incident in its `incident_service.investigations` table. Re-running an investigation replaces that incident's latest snapshot rather than retaining an unbounded report history. Data is collected through existing service APIs; the service does not query Order, Inventory, or Payment tables directly. The Gateway bounds forwarded responses at 1 MiB and allows up to 10 seconds for an investigation request, which may query several bounded sources.

On 2026-10-12, the isolated Investigation suite passed **65 tests**, the pinned JDK 21 Gateway suite passed **9 tests**, frontend tests passed **14 tests**, and the production build passed. A live request against an existing resolved service incident returned HTTP 200 with a `COMPLETE` result and 8 evidence items; its latest-result read matched. After restarting only the Investigation Service, the same result ID and generation timestamp remained available. The in-app browser rendered the empty-open and current-freshness states, then displayed a real resolved incident's saved investigation with cited facts, uncertainty, a trace gap, source freshness, and collected evidence. Browser console/network logs and mobile layout were not inspected. Remote CI, production authorization, and separate database-role enforcement are still outstanding. See [ADR 0008](docs/adr/0008-evidence-backed-investigation.md) and [TASKS.md](TASKS.md).

## Phase 7 evaluation and resilience

Run the fixed `traceforge-investigation-phase7-v1` scenario suite with the isolated test database:

```powershell
$env:DOCKER_CONTEXT = 'desktop-linux'
.\scripts\test-investigation.ps1
```

The script uses the `test` Compose profile and a disposable tmpfs PostgreSQL service; it does not use the persistent application schema or named volumes. It prints a `PHASE7_EVALUATION=` JSON line with scenario and metric results. On 2026-10-12 the full Investigation suite passed **72 tests**, and the focused evaluator passed again after its healthy-rule assertions were added. The 10 API cases include an unknown-incident request, current/stale/missing service observations, successful/unavailable trace reads, current/partial/unavailable Order observations, a compensated decline contradicting an open episode, and terminal compensation for a resolved episode. Separate rule checks verify that a fresh UP probe and a confirmed order produce no finding.

The latest recorded evaluation run reported top-1 root-cause accuracy **0/1**, top-3 recall **0/1**, citation validity **47/47**, unsupported factual claims **0/26** under the fixture-backed typed-evidence oracle, and persisted API latency p50 **38.943 ms** / p95 **42.629 ms** across 10 successful POST runs. The deterministic report API has no ranked root-cause field, so the one determinate case is counted as an explicit abstention; this is a measured limitation, not an accuracy pass threshold. The factual review is automated against fixed evidence and exact wording, not an independent blind review. Latency uses fixed in-process upstream fixtures and is not a production SLO. Cost is unavailable because no metered external provider is configured.

The suite exercises bounded Order and trace client failures, plus injected provider and PostgreSQL persistence failures. Provider/persistence failures return safe 503 codes, save no report, and leave incident lifecycle unchanged. Repeat/concurrent writes retain one latest snapshot per incident. The evaluation also checks source-freshness values and uncertainty wording; this exposed and fixed stale health being described as current. It verifies that a terminal `CONFIRMED` order returns `RESOLVE` without a finding or incident row when there is no open episode. The latest Phase 8 rerun passed all 72 Investigation tests in 4.62s and produced the metrics above, against the isolated tmpfs database. See [evaluation results](docs/evaluation.md), [ADR 0009](docs/adr/0009-investigation-evaluation-and-resilience.md), and [TASKS.md](TASKS.md).

## Phase 8 release-readiness check

On 2026-10-12, `npm test` passed 14 tests across 3 files, `npm run build` passed, `docker --context desktop-linux compose config -q` passed, and the isolated Investigation suite passed 72 tests in 4.62s. A separate disposable nine-service Compose project was built and cold-started with a project-generated network, a unique PostgreSQL volume, tmpfs Tempo storage, and loopback-only test ports. All nine services became healthy. Read-only checks returned HTTP 200 for Gateway health, the seeded `SKU-ALPHA` inventory read (12 available), Investigation `/readyz`, Grafana `/api/health`, detection status, and the open incident list; detection reached `CURRENT` with all four monitored services `UP/CURRENT`, and no incidents were open. The exact disposable containers, network, images, and PostgreSQL volume were cleaned. Before/after inspection showed the existing nine-service project and its three named volumes unchanged; it remained running throughout, and no application records were changed. Earlier Chrome checks cover selected desktop views only; mobile and exhaustive browser coverage remain unverified. The GitHub Actions workflow was inspected, but hosted CI for the uncommitted working-tree changes was not run; `gh` is unavailable. Production authorization and separate PostgreSQL role enforcement remain unverified. See the [runbook](docs/runbook.md) and [release status](docs/roadmap.md).

## Consistency guarantees and limits

Each service commits only to its own schema; there is no distributed transaction. The order row is durable before downstream calls. Inventory commits a stock decrement and reservation together; release restores that quantity and records `released_at` in one transaction and is idempotent by order ID. Payment commits an authorization/decline keyed by the order UUID. The saga uses persisted state transitions and compare-and-set updates, idempotency keys, bounded retries, and compensation.

This does not provide exactly-once execution. A timeout can hide a successful reservation or authorization commit, so the order records an unknown outcome and retries the same idempotency key. The order reports a reservation ID only after Inventory confirms it. A payment decline is not terminal until inventory release succeeds. If the process or database is unavailable during compensation, `COMPENSATION_REQUIRED` remains persisted for later recovery. The three schemas share one PostgreSQL server and local credentials; this is a development sample, not a production security/availability design.

A payment idempotency-key conflict is held at `INVENTORY_RESERVED` for manual review; the system does not release stock while the conflicting key could refer to an existing authorization.

## Verify

```powershell
.\scripts\test-backend.ps1
.\scripts\test-investigation.ps1
cd frontend
npm test
npm run build
cd ..
docker compose config -q
```

The backend script builds/starts the full Compose stack, runs Gateway, Inventory, Payment, and real-network Order integration suites in one-shot `maven:3.9.16-eclipse-temurin-21` containers, checks saga recovery after service restarts, and runs Tempo trace assertions. The Maven cache is stored in the `traceforge-maven-cache` Docker volume. `OrderTracingTest` separately checks new-root recovery spans and origin links with an in-memory test exporter. Exact verified test counts and live trace IDs/results are recorded in [TASKS.md](TASKS.md); configured telemetry is not considered verified until the script reads matching spans from Tempo.

`scripts/test-investigation.ps1` builds the pinned Python investigation image and runs its tests against a separate PostgreSQL service using tmpfs storage and an isolated Compose project; it does not use the persistent application schemas or volumes. It removes only that temporary test database container when finished.

On 2026-10-10, Phase 3 local verification queried real Tempo traces for success, unknown SKU, payment decline/compensation, and payment outage/recovery, including the caller-supplied W3C trace context and a recovery link. The earlier Chrome Overview spot-check showed gateway health HTTP 200 and the honest empty incident state; one cancelled health request was not diagnosed, and this was not exhaustive browser workflow testing. Remote CI was not run for that verification.

On 2026-10-10, the Phase 4 backend integration passed locally: `scripts/test-investigation.ps1` passed **53 tests** against its disposable tmpfs database. The final `scripts/test-backend.ps1` run passed **37 Java tests** (Gateway 3, Inventory 8, Payment 4, Order 22), saga recovery/restart assertions, and live Tempo and incident-detection verifiers. It verified incident opening, deduplication, source failure non-resolution, explicit terminal compensation resolution, persistence across Investigation restart, two-probe health opening/resolution, and detection continuing while the Collector was stopped. All **9** Compose services were healthy afterward; `docker compose config -q` and `git diff --check` passed. Frontend tests/build were not rerun in this backend-only stage because no frontend files changed; the earlier Phase 3 frontend results remain documented. The `SKU-TEST-ORDER` warning remains unchanged. Exact commands and trace evidence are in [TASKS.md](TASKS.md).

During the Phase 4 frontend dashboard milestone on 2026-10-12, `npm test` passed **9 tests** and `npm run build` passed. Read-only requests through the Vite proxy returned HTTP 200 for gateway health, open incidents, and detection status; the open list was empty and detection status was `CURRENT` with five sources. A desktop browser check verified the Overview, honest empty-open state, current freshness panel, resolved history, and a real resolved incident detail. The browser console had no errors or warnings, and the page had no horizontal overflow at 1280×720. Mobile rendering and exhaustive browser workflows remain unverified. `docker compose ps` was blocked by Docker named-pipe permissions at that earlier closeout, so Compose health was not freshly checked then. The later Phase 8 checks are recorded above. `origin` is configured, but remote CI has not been run or verified for this frontend change. The `SKU-TEST-ORDER` warning remains unchanged.

## Stop and reset

- Stop the dashboard with `Ctrl+C`.
- Stop Compose with `docker compose down`; the database volume remains.
- To intentionally erase stored orders, reservations, payment attempts, and retained traces, use `docker compose down -v`.

## Roadmap and references

See [docs/roadmap.md](docs/roadmap.md), [docs/architecture.md](docs/architecture.md), [docs/security.md](docs/security.md), [docs/adr/0004-persisted-payment-saga.md](docs/adr/0004-persisted-payment-saga.md), and [docs/adr/0005-distributed-tracing.md](docs/adr/0005-distributed-tracing.md). The standalone interview guide is at `E:\TraceForge_Interview_Guide.md` outside the repository.
