# TraceForge handoff

Snapshot prepared 2026-10-12 for a fresh Codex account. Read this with [`CODEX_GUIDE.md`](CODEX_GUIDE.md), then use [`NEXT_PROMPT.md`](NEXT_PROMPT.md) to continue the frontend milestone.

## Project and architecture

TraceForge is an evidence-first local incident investigation demo. The stack is React 19 + TypeScript + Vite, four Java 21 / Spring Boot services, a Python 3.12 / FastAPI investigation service, PostgreSQL 16, and a local OpenTelemetry Collector → Tempo → Grafana pipeline. Backend builds/tests use the pinned Docker image `maven:3.9.16-eclipse-temurin-21`; no host Maven installation is required.

| Component | Responsibility |
| --- | --- |
| API Gateway | Loopback-published entry point; proxies order and bounded incident/status reads. |
| Order Service | Owns durable orders and saga state; calls Inventory and Payment; performs scheduled recovery and compensation; provides private bounded recovery observations to the detector. |
| Inventory Service | Owns stock and idempotent reservations/releases. |
| Payment Service | Owns synthetic authorization/decline attempts; it is not a real payment provider. |
| Investigation Service | Runs scheduled deterministic health/recovery rules, tracks source freshness, persists incidents, and serves bounded read APIs. It does not query Tempo to decide incidents. |
| PostgreSQL | Shared local server with separate `order_service`, `inventory_service`, `payment_service`, and `incident_service` schemas. Schema ownership is logical; services share local credentials. |
| OpenTelemetry Collector / Tempo / Grafana | Local trace ingestion, storage/query, and Explore UI. Traces are optional supporting evidence for detection. |
| Frontend | Current React dashboard renders gateway health and an honest empty-state placeholder; incident APIs are not yet connected. |

Phase 3 added one pinned OpenTelemetry Java agent across the four Java services, W3C trace propagation, business/recovery spans, and queryable local Tempo traces. Phase 4 implemented the Investigation Service, PostgreSQL incident/freshness persistence, scheduled deterministic rules, bounded Order recovery observations, and gateway read proxies.

## Git and worktree state

At inspection, the branch was `master`, and HEAD was still the baseline commit `e30a826 chore: establish TraceForge foundation`. No later commit contains the current implementation. Before these handoff files were added, `git status --short --untracked-files=all` showed **26 modified tracked files and 45 untracked files**. `git diff --stat` showed 26 tracked files, 1,039 insertions, and 131 deletions (untracked files are excluded). `git diff --cached --stat` was empty. Immediately after adding these three files, the worktree showed 26 modified tracked files and 48 untracked files; the staged diff remained empty. Important Phase 3 and Phase 4 implementation is uncommitted.

Modified tracked files at that snapshot:

```text
.env.example
.github/workflows/ci.yml
README.md
TASKS.md
compose.yaml
docs/architecture.md
docs/roadmap.md
docs/security.md
scripts/test-backend.ps1
scripts/verify-saga-recovery.ps1
services/api-gateway/Dockerfile
services/api-gateway/src/main/resources/application.properties
services/inventory-service/Dockerfile
services/inventory-service/pom.xml
services/inventory-service/src/main/java/com/traceforge/inventory/InventoryController.java
services/inventory-service/src/test/java/com/traceforge/inventory/InventoryControllerTest.java
services/order-service/Dockerfile
services/order-service/pom.xml
services/order-service/src/main/java/com/traceforge/order/OrderApplicationService.java
services/order-service/src/main/java/com/traceforge/order/OrderController.java
services/order-service/src/main/java/com/traceforge/order/OrderRepository.java
services/order-service/src/test/java/com/traceforge/order/OrderControllerTest.java
services/payment-service/Dockerfile
services/payment-service/pom.xml
services/payment-service/src/main/java/com/traceforge/payment/PaymentController.java
services/payment-service/src/test/java/com/traceforge/payment/PaymentControllerTest.java
```

Untracked implementation files at that snapshot:

```text
docs/adr/0005-distributed-tracing.md
docs/adr/0006-deterministic-incident-detection.md
investigation/.dockerignore
investigation/Dockerfile
investigation/migrations/0001_incidents_and_health_state.sql
investigation/migrations/0002_detection_cycles_and_source_freshness.sql
investigation/pyproject.toml
investigation/requirements-dev.txt
investigation/requirements.txt
investigation/tests/__init__.py
investigation/tests/conftest.py
investigation/tests/helpers.py
investigation/tests/test_clients.py
investigation/tests/test_main.py
investigation/tests/test_postgres_repository.py
investigation/tests/test_rules.py
investigation/tests/test_scheduler.py
investigation/traceforge_investigation/__init__.py
investigation/traceforge_investigation/clients.py
investigation/traceforge_investigation/config.py
investigation/traceforge_investigation/engine.py
investigation/traceforge_investigation/main.py
investigation/traceforge_investigation/models.py
investigation/traceforge_investigation/repository.py
investigation/traceforge_investigation/rules.py
investigation/traceforge_investigation/scheduler.py
observability/grafana/provisioning/datasources/tempo.yaml
observability/otel-collector.yaml
observability/otel-collector/Dockerfile
observability/tempo.yaml
observability/tempo/Dockerfile
scripts/TraceForgeTestData.ps1
scripts/test-investigation.ps1
scripts/verify-detection.ps1
scripts/verify-traces.ps1
services/api-gateway/src/main/java/com/traceforge/gateway/IncidentProxyController.java
services/api-gateway/src/main/java/com/traceforge/gateway/InvestigationClient.java
services/api-gateway/src/test/java/com/traceforge/gateway/IncidentProxyControllerTest.java
services/order-service/src/main/java/com/traceforge/order/OrderAttention.java
services/order-service/src/main/java/com/traceforge/order/OrderAttentionPage.java
services/order-service/src/main/java/com/traceforge/order/OrderRecoveryObservationPage.java
services/order-service/src/main/java/com/traceforge/order/OrderTracing.java
services/order-service/src/main/resources/db/migration/V3__add_recovery_trace_link.sql
services/order-service/src/test/java/com/traceforge/order/OrderAttentionControllerTest.java
services/order-service/src/test/java/com/traceforge/order/OrderTracingTest.java
```

Refresh Git status before any future edit; this list is a handoff snapshot, not permission to overwrite anything.

## Verification baseline and uncertainty

The following are **reported results from the 2026-10-10 verification recorded in this conversation and `TASKS.md`**. They were not rerun while preparing this handoff:

- `.\scripts\test-investigation.ps1`: 53 tests passed against disposable tmpfs PostgreSQL.
- `.\scripts\test-backend.ps1`: Gateway 3, Inventory 8, Payment 4, Order 22; **37 Java tests, 0 failures, 0 errors, 0 skipped**, plus saga restart/recovery, Tempo, and live detection checks.
- `docker compose config -q` and `git diff --check` passed; all nine default Compose services were healthy after verification.
- Tempo was queried for real traces: successful order `14654c73679a45bf838ee72a26ffb933`; unknown SKU `91b5171abf7e4826b446516b2f0df729`; payment decline/compensation `de6e500a7d0b47b68cf2ae91902991b6`; payment outage/recovery `d451343aa189419fb49a00e3d62d9753`, with a recovery span linked to the originating order span.
- Live detection checks covered non-incidents for healthy/fully compensated outcomes; opening and deduplication; source-failure non-resolution; resolution only with terminal order and compensation evidence; two-probe health open/resolve; persistence of incident and freshness through Investigation restart; and cycles continuing with Collector stopped.
- Earlier Phase 3 results: two serial backend runs each passed 27 Java tests; frontend tests passed 2 tests and the production build passed. Frontend tests/build were **not rerun** in the Phase 4 backend-only stage.

Still unverified: frontend incident dashboard and its browser workflow; exhaustive browser rendering (only a Phase 3 Chrome Overview spot-check exists); remote CI (the project reports no Git remote configured); production authorization and separate database-role boundaries. In the earlier browser spot-check, one health request was cancelled and another succeeded; the cancellation was not diagnosed, and no TraceForge app error was identified in the supplied console output.

## Compose services and local endpoints

The default Compose stack has nine services. Only the gateway, Tempo query API, and Grafana are published on loopback. Other service ports below are private to `traceforge-network`.

| Service | Internal port | Local access |
| --- | ---: | --- |
| `api-gateway` | 8080 | `http://localhost:8080` |
| `order-service` | 8082 | Compose network only |
| `inventory-service` | 8081 | Compose network only |
| `payment-service` | 8083 | Compose network only |
| `investigation-service` | 8090 | Compose network only |
| `postgres` | 5432 | Compose network only |
| `otel-collector` | OTLP 4317/4318; health 13133 | Compose network only |
| `tempo` | query 3200; OTLP receiver private | `http://localhost:3200` |
| `grafana` | 3000 | `http://localhost:3000` |

The Vite dev server normally uses `http://localhost:5173` and proxies `/api` to gateway port 8080. The `test` Compose profile adds `incident-test-postgres` (tmpfs-only) and `investigation-test`; these are not default application services.

Useful gateway endpoints:

```text
GET  /api/v1/health
GET  /api/v1/incidents?status=OPEN|RESOLVED&limit=1..100&cursor=<opaque>
GET  /api/v1/incidents/{uuid}
GET  /api/v1/detection-status
```

List defaults to `status=OPEN`, `limit=50`. Its JSON has `items`, `limit`, nullable `nextCursor`, and `detectionStatus`. Incident items contain real `id`, `ruleKey`, `ruleVersion`, `severity`, `status`, `scopeType`, `sourceReference`, timestamps, nullable `resolvedAt`, `occurrenceCount`, `summary`, bounded `evidence`, nullable `originTraceId`, and metadata. Evidence includes `sourceType`, `sourceId`, `observedAt`, fixed `signalCode`, and nullable `traceId`. Detail returns one incident (404 if absent); database failures return a safe 503.

Detection status is `NOT_RUN`, `CURRENT`, `PARTIAL`, `STALE`, or `UNAVAILABLE`, with optional `latestCycle` and per-source freshness. A source has `source`, `status` (`CURRENT`, `PARTIAL`, `STALE`, `UNAVAILABLE`), `attemptedAt`, nullable `lastSuccessAt`, `itemCount`, and nullable `errorCode`. An empty successful incident page is not a statement that sources are healthy; use the freshness fields. Failed, incomplete, stale, unknown, or missing inputs never resolve an incident.

Rules: `SERVICE_NOT_READY` opens after two consecutive failed/timed-out/non-UP probes and resolves after two consecutive UP probes. `ORDER_RECOVERY_STALLED` covers overdue recovery or required incomplete compensation and resolves only from explicit terminal Order state plus completed compensation. Confirmed orders and fully compensated payment declines are ordinary outcomes. Repeated findings update one open episode by stable fingerprint; a later recurrence may open a new episode.

## Safe commands and next work

```powershell
docker compose up --build -d --wait
.\scripts\test-investigation.ps1
.\scripts\test-backend.ps1
.\scripts\verify-saga-recovery.ps1
.\scripts\verify-detection.ps1
.\scripts\verify-traces.ps1
cd frontend
npm test
npm run build
npm run dev
```

The test scripts have different effects. `test-investigation.ps1` uses the isolated test profile and tmpfs database. `test-backend.ps1` rebuilds/starts services and runs backend, saga, trace, and detection checks. `verify-detection.ps1` temporarily stops/restarts Order, Inventory, Collector, and Investigation, creates scoped synthetic records, restores services in `finally`, cleans its own generated business rows and order incidents, and intentionally retains service-health incident history. `verify-traces.ps1` creates local business test data and temporarily stops Collector; it restores Collector, but its successful-order scenarios can consume inventory. Inspect scripts before rerunning them. Do not run `docker compose down -v`.

Next milestone: build the frontend incident dashboard against the existing API contracts, add frontend tests, run `npm run build`, and verify the running browser view if browser tooling is available. Do not rewrite the backend or invent endpoints. Preserve the known legacy warning: `SKU-TEST-ORDER` has 94 available units but 113 reservation rows representing 139 unreleased units. Do not reconcile those rows, reuse that SKU in tests, reset the application database, or delete the named `traceforge-postgres-data` / `traceforge-tempo-data` volumes.
