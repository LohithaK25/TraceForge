# TraceForge handoff

Updated 2026-10-12. Read this with [`CODEX_GUIDE.md`](CODEX_GUIDE.md) and inspect the live worktree before continuing. Phase 6 evidence-backed investigation is implemented and locally verified through automated tests, live API/persistence checks, and browser review of a real resolved incident's saved investigation. Remote CI, production authorization, separate database-role enforcement, mobile layout, and browser console/network logs remain unverified. Preserve all changes and the legacy database warning below.

## Project and architecture

TraceForge is an evidence-first local incident investigation demo. The stack is React 19 + TypeScript + Vite, four Java 21 / Spring Boot services, a Python 3.12 / FastAPI investigation service, PostgreSQL 16, and a local OpenTelemetry Collector → Tempo → Grafana pipeline. Backend builds/tests use the pinned Docker image `maven:3.9.16-eclipse-temurin-21`; no host Maven installation is required.

| Component | Responsibility |
| --- | --- |
| API Gateway | Loopback-published entry point; proxies order, bounded incident/status reads, and a bounded sanitized Tempo trace summary. |
| Order Service | Owns durable orders and saga state; calls Inventory and Payment; performs scheduled recovery and compensation; provides private bounded recovery observations to the detector. |
| Inventory Service | Owns stock and idempotent reservations/releases. |
| Payment Service | Owns synthetic authorization/decline attempts; it is not a real payment provider. |
| Investigation Service | Runs scheduled deterministic health/recovery rules, tracks source freshness, persists incidents, and serves bounded read APIs. It also collects and persists an on-demand evidence-backed investigation snapshot per incident. It does not query Tempo to decide incidents. |
| PostgreSQL | Shared local server with separate `order_service`, `inventory_service`, `payment_service`, and `incident_service` schemas. Schema ownership is logical; services share local credentials. |
| OpenTelemetry Collector / Tempo / Grafana | Local trace ingestion, storage/query, and Explore UI. Traces are optional supporting evidence for detection. |
| Frontend | React dashboard renders gateway health, incidents, persisted per-service health snapshots, detection-source freshness, on-demand trace summaries, and saved/on-demand evidence-backed investigations through the gateway. |

Phase 3 added one pinned OpenTelemetry Java agent across the four Java services, W3C trace propagation, business/recovery spans, and queryable local Tempo traces. Phase 4 implemented the Investigation Service, PostgreSQL incident/freshness persistence, scheduled deterministic rules, bounded Order recovery observations, and gateway read proxies. Phase 6 added bounded evidence collection from fixed service APIs, validated/cited deterministic reports, latest-report persistence, Gateway proxies, and the incident-detail Investigation panel. It does not call an external LLM or change deterministic incident lifecycle.

## Git and worktree state

This checkout is on `feature/phase4-incident-dashboard` at `809cd8d` (`docs: finalize Phase 5 verification and Phase 6 handoff`), tracking `origin/feature/phase4-incident-dashboard`. This is the committed Phase 5 checkpoint; Phase 6 implementation is uncommitted. The final inspection found 17 modified tracked files and 11 untracked Phase 6 files; the staged diff is empty. Preserve every change. Nothing has been staged, committed, or pushed in Phase 6. The `origin` remote is configured, but remote CI has not been verified.

Phase 6 adds Investigation result models, fixed-source evidence collection, a bounded trace client, JSONB persistence migration and repository/API, fixed Gateway proxies, the incident-detail investigation panel and tests, plus documentation and ADR 0008. The complete current file list is in `git status`; preserve all of it.

## Verification baseline and uncertainty

The following results are the earlier Phase 4/observability baseline recorded in `TASKS.md`; the Phase 5 work below did not rerun the unrelated Order, Inventory, and Payment suites or the full saga/trace backend script:

- Investigation Service: **53 tests passed** against disposable tmpfs PostgreSQL.
- Pinned Java backend: **37 tests passed**, 0 failures/errors/skips, plus saga restart/recovery, Tempo trace queries, and live incident detection checks.
- The reported live checks covered trace propagation/linking; incident opening, deduplication, resolution, freshness and restart persistence; and detection while Collector was stopped. All nine Compose services were healthy after that run, and Compose configuration passed.
- Earlier Phase 3 verification reported two serial 27-test backend runs, frontend tests/build, and a Chrome Overview spot-check. The spot-check showed health HTTP 200 and an honest empty state. DevTools showed a cancelled and a successful health request; the cancellation was not diagnosed, and the supplied console output identified no TraceForge application error.

Phase 5 recovery on 2026-10-12 found that the `default` Docker context targeted `npipe:////./pipe/docker_engine` and returned permission denied, while the `desktop-linux` context at `npipe:////./pipe/dockerDesktopLinuxEngine` connected to Docker Desktop. Tests used `$env:DOCKER_CONTEXT = 'desktop-linux'` per process; persistent Docker settings were not changed.

Phase 5 local backend results: Investigation **54 tests passed** in its tmpfs PostgreSQL project; the pinned JDK 21/Maven Gateway suite **8 tests passed**. The test run fixed a frozen-clock test bug, a missing Java import, and Spring constructor selection. Only Gateway and Investigation were built/force-recreated; their running image IDs matched the fresh tags. The live detection verifier passed controlled opening/deduplication/resolution, stale/failure non-resolution, persistence through Investigation restart, and detection while Collector was stopped. A real read-only caller trace queried through the rebuilt Gateway returned four sanitized spans from Gateway and Inventory; invalid/missing/Tempo-unavailable cases returned 400/404/503, and Tempo was restored. The frontend's **11 tests** and production build passed earlier in Phase 5 and were not rerun because frontend source did not change.

An earlier browser-automation attempt blocked navigation to `http://127.0.0.1:5173/` under its local URL security policy. The subsequently supplied four desktop screenshots manually document the per-service probe results/freshness, separate detection-source freshness, honest empty-open state, real resolved `SERVICE_NOT_READY` history, a detail view with `HEALTH_PROBE` / `CONNECT_FAILED` evidence, and the trace-evidence section when the incident has no trace references. This is screenshot evidence for those visible desktop states only; it does not establish every interaction, browser network request, mobile layout, or exhaustive workflow. Remote CI, production authorization, and separate database-role enforcement remain outstanding. The legacy `SKU-TEST-ORDER` state remains inconsistent (94 available units versus 113 reservation rows representing 139 unreleased units); do not alter it.

Phase 6 verification on 2026-10-12 is recorded in the Phase 6 section at the top of `TASKS.md`: 65 isolated Investigation tests, 9 pinned Gateway tests, 14 frontend tests, and the frontend production build passed. Compose config validation passed; the nine services were healthy before the targeted Investigation restart. A live investigation POST/GET returned a cited `COMPLETE` report with 8 evidence items and one optional trace gap, and the same report ID/timestamp survived an Investigation Service restart. The in-app browser showed the Overview empty-open/freshness state and a real resolved incident's saved investigation with citations, uncertainty, source freshness, trace gap, and evidence. Browser console/network logs and mobile layout were not checked. During closeout, Docker context/config and named-pipe access both returned `Access is denied`, so no fresh post-restart Compose health snapshot is claimed. No full backend script or remote CI run was performed. Production authorization and separate database-role enforcement remain unverified.

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
GET  /api/v1/incidents/{uuid}/investigations/latest
POST /api/v1/incidents/{uuid}/investigations
```

List defaults to `status=OPEN`, `limit=50`. Its JSON has `items`, `limit`, nullable `nextCursor`, and `detectionStatus`. Incident items contain real `id`, `ruleKey`, `ruleVersion`, `severity`, `status`, `scopeType`, `sourceReference`, timestamps, nullable `resolvedAt`, `occurrenceCount`, `summary`, bounded `evidence`, nullable `originTraceId`, and metadata. Evidence includes `sourceType`, `sourceId`, `observedAt`, fixed `signalCode`, and nullable `traceId`. Detail returns one incident (404 if absent); database failures return a safe 503.

Detection status is `NOT_RUN`, `CURRENT`, `PARTIAL`, `STALE`, or `UNAVAILABLE`, with optional `latestCycle`, per-source freshness, and a four-entry `services` array. Service entries carry persisted last probe status (`UP`, `DOWN`, `TIMEOUT`, `UNKNOWN`), nullable `observedAt`, `freshnessStatus`, and `incidentOpen`. This is the last collected state, not a live browser probe. Empty/missing/stale data is not confirmed healthy; failed, incomplete, stale, unknown, or missing inputs never resolve an incident. `GET /api/v1/traces/{traceId}` returns a bounded sanitized span summary through the Gateway; Tempo unavailable (503) and trace missing/expired (404) remain unavailable evidence, not healthy or resolved state.

The investigation routes collect/read the latest persisted report for an existing incident. An existing incident with no saved run returns `404 INVESTIGATION_NOT_FOUND`; an unknown incident has a distinct not-found code. A run updates only the Investigation-owned `incident_service.investigations` snapshot. Reports separate facts, hypotheses, cited actions, evidence gaps, source freshness, and uncertainty, with `COMPLETE`, `PARTIAL`, or `INSUFFICIENT` source-completeness status. The fixed `deterministic-v1` provider makes no external LLM call. Collection is bounded to known trace IDs, 3 traces, 20 spans per trace, 100 evidence items, 1 MiB trace responses, and 256 KiB persisted report JSON; the Gateway read timeout is 10 seconds.

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

Next milestone: Phase 7 evaluation and resilience, following `docs/roadmap.md`. Refresh Git state and inspect the actual Phase 6 implementation before planning it; do not rebuild Phase 6. `NEXT_PROMPT.md` still contains an earlier frontend continuation prompt and should not override the roadmap. Preserve the remote-CI, production-authorization, and separate database-role-enforcement caveats. Preserve the known legacy warning: `SKU-TEST-ORDER` has 94 available units but 113 reservation rows representing 139 unreleased units. Do not reconcile those rows, reuse that SKU in tests, reset the application database, or delete the named `traceforge-postgres-data` / `traceforge-tempo-data` volumes.
