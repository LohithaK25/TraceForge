# TraceForge handoff

Snapshot prepared 2026-10-12 for a fresh Codex account. Read this with [`CODEX_GUIDE.md`](CODEX_GUIDE.md), then follow the next user-provided scope. Phase 4 dashboard browser closeout is complete for the verified desktop states below.

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
| Frontend | React dashboard renders gateway health and consumes the bounded incident list/detail and detection-freshness APIs through the gateway. |

Phase 3 added one pinned OpenTelemetry Java agent across the four Java services, W3C trace propagation, business/recovery spans, and queryable local Tempo traces. Phase 4 implemented the Investigation Service, PostgreSQL incident/freshness persistence, scheduled deterministic rules, bounded Order recovery observations, and gateway read proxies.

## Git and worktree state

This checkout is on feature/phase4-incident-dashboard at a9ce4a5 (chore: snapshot Phase 4 before frontend). The local backup/pre-frontend-handoff branch tracks origin/backup/pre-frontend-handoff at the same commit; master remains at e30a826. An origin remote is configured, but this frontend branch has no upstream and no remote CI result has been verified. The backend/observability implementation is preserved in the current commit.

The dashboard and documentation updates in this worktree are uncommitted. The frontend implementation files are modified frontend/src/App.tsx, frontend/src/App.test.tsx, and frontend/src/styles.css, plus untracked frontend/src/api/incidents.ts, frontend/src/components/IncidentDashboard.tsx, and frontend/src/components/IncidentDashboard.test.tsx. README, task log, handoff, architecture, roadmap, security, ADR 0006, and next-prompt documentation also contain current-session updates. The last inspected staged diff was empty; inspect git status --short --untracked-files=all again before continuing. Do not stage, commit, push, reset, stash, revert, or discard anything.

## Verification baseline and uncertainty

The following backend results were reported for the 2026-10-10 verification and are recorded in `TASKS.md`; they were **not rerun** in the 2026-10-12 frontend session:

- Investigation Service: **53 tests passed** against disposable tmpfs PostgreSQL.
- Pinned Java backend: **37 tests passed**, 0 failures/errors/skips, plus saga restart/recovery, Tempo trace queries, and live incident detection checks.
- The reported live checks covered trace propagation/linking; incident opening, deduplication, resolution, freshness and restart persistence; and detection while Collector was stopped. All nine Compose services were healthy after that run, and Compose configuration passed.
- Earlier Phase 3 verification reported two serial 27-test backend runs, frontend tests/build, and a Chrome Overview spot-check. The spot-check showed health HTTP 200 and an honest empty state. DevTools showed a cancelled and a successful health request; the cancellation was not diagnosed, and the supplied console output identified no TraceForge application error.

This session passed `npm test` (**9 tests**) and `npm run build`. Read-only Vite-proxy calls returned HTTP 200 for health, the open incident list (0 items, detection `CURRENT`), and detection status (`CURRENT`, five sources). The desktop browser rendered the Overview, empty open-incidents state, five-source freshness panel, resolved history, and a real resolved `SERVICE_NOT_READY` detail with evidence. No console errors or warnings were returned, and no horizontal overflow was measured at 1280×720. Mobile and exhaustive browser workflows remain unverified. `docker compose ps` was blocked by Docker named-pipe permissions. Remote CI, production authorization, and separate database-role enforcement remain outstanding. The legacy `SKU-TEST-ORDER` state remains inconsistent (94 available units versus 113 reservation rows representing 139 unreleased units); do not alter it.

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

The frontend incident dashboard and desktop browser closeout are complete for the documented states. Do not start another feature until the user provides its scope. Do not rewrite the backend or invent endpoints. Preserve the known legacy warning: `SKU-TEST-ORDER` has 94 available units but 113 reservation rows representing 139 unreleased units. Do not reconcile those rows, reuse that SKU in tests, reset the application database, or delete the named `traceforge-postgres-data` / `traceforge-tempo-data` volumes.
