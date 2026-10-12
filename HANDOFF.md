# TraceForge handoff

Updated 2026-10-12. Read this with [`CODEX_GUIDE.md`](CODEX_GUIDE.md) and inspect the live worktree before continuing. Phase 4 is preserved. Phase 5 backend/runtime checks are locally verified for the documented scope, and the supplied four desktop screenshots document the Overview, freshness, empty-open, resolved-history, incident-detail, and trace-evidence views. Mobile and exhaustive browser workflows remain unverified.

## Project and architecture

TraceForge is an evidence-first local incident investigation demo. The stack is React 19 + TypeScript + Vite, four Java 21 / Spring Boot services, a Python 3.12 / FastAPI investigation service, PostgreSQL 16, and a local OpenTelemetry Collector → Tempo → Grafana pipeline. Backend builds/tests use the pinned Docker image `maven:3.9.16-eclipse-temurin-21`; no host Maven installation is required.

| Component | Responsibility |
| --- | --- |
| API Gateway | Loopback-published entry point; proxies order, bounded incident/status reads, and a bounded sanitized Tempo trace summary. |
| Order Service | Owns durable orders and saga state; calls Inventory and Payment; performs scheduled recovery and compensation; provides private bounded recovery observations to the detector. |
| Inventory Service | Owns stock and idempotent reservations/releases. |
| Payment Service | Owns synthetic authorization/decline attempts; it is not a real payment provider. |
| Investigation Service | Runs scheduled deterministic health/recovery rules, tracks source freshness, persists incidents, and serves bounded read APIs. It does not query Tempo to decide incidents. |
| PostgreSQL | Shared local server with separate `order_service`, `inventory_service`, `payment_service`, and `incident_service` schemas. Schema ownership is logical; services share local credentials. |
| OpenTelemetry Collector / Tempo / Grafana | Local trace ingestion, storage/query, and Explore UI. Traces are optional supporting evidence for detection. |
| Frontend | React dashboard renders gateway health, incidents, persisted per-service health snapshots, detection-source freshness, and on-demand trace summaries through the gateway. |

Phase 3 added one pinned OpenTelemetry Java agent across the four Java services, W3C trace propagation, business/recovery spans, and queryable local Tempo traces. Phase 4 implemented the Investigation Service, PostgreSQL incident/freshness persistence, scheduled deterministic rules, bounded Order recovery observations, and gateway read proxies.

## Git and worktree state

This checkout is on `feature/phase4-incident-dashboard` at `8209ac1` (`feat: complete Phase 4 incident dashboard`) and tracks `origin/feature/phase4-incident-dashboard`. `backup/pre-frontend-handoff` remains at `a9ce4a5`; `master` remains at `e30a826`. The worktree was clean at Phase 5 start. Phase 5 changes are now uncommitted; inspect `git status --short --untracked-files=all`. At the start of the 2026-10-12 documentation closeout, status showed 18 modified tracked files and 9 untracked files; after this docs-only closeout it shows 19 modified tracked files and 9 untracked files, with an empty staged diff. Nothing has been staged, committed, or pushed. The `origin` remote exists; remote CI has not been verified.

Phase 5 changed `compose.yaml`, the Gateway Java sources/tests/configuration, Investigation models/repository/tests, frontend Overview/API/components/styles/tests, and README/TASKS/HANDOFF/NEXT_PROMPT plus architecture, security, roadmap, and ADR 0007. The complete current list is in `git status`; preserve all of it.

## Verification baseline and uncertainty

The following results are the earlier Phase 4/observability baseline recorded in `TASKS.md`; the Phase 5 work below did not rerun the unrelated Order, Inventory, and Payment suites or the full saga/trace backend script:

- Investigation Service: **53 tests passed** against disposable tmpfs PostgreSQL.
- Pinned Java backend: **37 tests passed**, 0 failures/errors/skips, plus saga restart/recovery, Tempo trace queries, and live incident detection checks.
- The reported live checks covered trace propagation/linking; incident opening, deduplication, resolution, freshness and restart persistence; and detection while Collector was stopped. All nine Compose services were healthy after that run, and Compose configuration passed.
- Earlier Phase 3 verification reported two serial 27-test backend runs, frontend tests/build, and a Chrome Overview spot-check. The spot-check showed health HTTP 200 and an honest empty state. DevTools showed a cancelled and a successful health request; the cancellation was not diagnosed, and the supplied console output identified no TraceForge application error.

Phase 5 recovery on 2026-10-12 found that the `default` Docker context targeted `npipe:////./pipe/docker_engine` and returned permission denied, while the `desktop-linux` context at `npipe:////./pipe/dockerDesktopLinuxEngine` connected to Docker Desktop. Tests used `$env:DOCKER_CONTEXT = 'desktop-linux'` per process; persistent Docker settings were not changed.

Phase 5 local backend results: Investigation **54 tests passed** in its tmpfs PostgreSQL project; the pinned JDK 21/Maven Gateway suite **8 tests passed**. The test run fixed a frozen-clock test bug, a missing Java import, and Spring constructor selection. Only Gateway and Investigation were built/force-recreated; their running image IDs matched the fresh tags. The live detection verifier passed controlled opening/deduplication/resolution, stale/failure non-resolution, persistence through Investigation restart, and detection while Collector was stopped. A real read-only caller trace queried through the rebuilt Gateway returned four sanitized spans from Gateway and Inventory; invalid/missing/Tempo-unavailable cases returned 400/404/503, and Tempo was restored. The frontend's **11 tests** and production build passed earlier in Phase 5 and were not rerun because frontend source did not change.

An earlier browser-automation attempt blocked navigation to `http://127.0.0.1:5173/` under its local URL security policy. The subsequently supplied four desktop screenshots manually document the per-service probe results/freshness, separate detection-source freshness, honest empty-open state, real resolved `SERVICE_NOT_READY` history, a detail view with `HEALTH_PROBE` / `CONNECT_FAILED` evidence, and the trace-evidence section when the incident has no trace references. This is screenshot evidence for those visible desktop states only; it does not establish every interaction, browser network request, mobile layout, or exhaustive workflow. Remote CI, production authorization, and separate database-role enforcement remain outstanding. The legacy `SKU-TEST-ORDER` state remains inconsistent (94 available units versus 113 reservation rows representing 139 unreleased units); do not alter it.

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
GET  /api/v1/traces/{32-lowercase-hex-trace-id}
```

List defaults to `status=OPEN`, `limit=50`. Its JSON has `items`, `limit`, nullable `nextCursor`, and `detectionStatus`. Incident items contain real `id`, `ruleKey`, `ruleVersion`, `severity`, `status`, `scopeType`, `sourceReference`, timestamps, nullable `resolvedAt`, `occurrenceCount`, `summary`, bounded `evidence`, nullable `originTraceId`, and metadata. Evidence includes `sourceType`, `sourceId`, `observedAt`, fixed `signalCode`, and nullable `traceId`. Detail returns one incident (404 if absent); database failures return a safe 503.

Detection status is `NOT_RUN`, `CURRENT`, `PARTIAL`, `STALE`, or `UNAVAILABLE`, with optional `latestCycle`, per-source freshness, and a four-entry `services` array. Service entries carry persisted last probe status (`UP`, `DOWN`, `TIMEOUT`, `UNKNOWN`), nullable `observedAt`, `freshnessStatus`, and `incidentOpen`. This is the last collected state, not a live browser probe. Empty/missing/stale data is not confirmed healthy; failed, incomplete, stale, unknown, or missing inputs never resolve an incident. `GET /api/v1/traces/{traceId}` returns a bounded sanitized span summary through the Gateway; Tempo unavailable (503) and trace missing/expired (404) remain unavailable evidence, not healthy or resolved state.

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

Next milestone: Phase 6 evidence-backed investigation, following the acceptance scope in `docs/roadmap.md` and the current architecture. Refresh Git state before any work and inspect the Phase 6 contracts and relevant implementation. Phase 5 desktop screenshot evidence does not establish mobile or exhaustive browser behavior. Preserve the remote-CI, production-authorization, and separate database-role-enforcement caveats. Preserve the known legacy warning: `SKU-TEST-ORDER` has 94 available units but 113 reservation rows representing 139 unreleased units. Do not reconcile those rows, reuse that SKU in tests, reset the application database, or delete the named `traceforge-postgres-data` / `traceforge-tempo-data` volumes.
