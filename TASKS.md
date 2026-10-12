# TraceForge task log

## Phase 8 release readiness and interview guide — 2026-10-12

### Acceptance checklist

| Roadmap criterion | Status and evidence |
| --- | --- |
| Clean startup | **Verified locally.** A disposable cold start of all nine Compose services reached healthy status. Gateway health, seeded inventory read, Investigation readiness, Grafana health, detection status, and open-incident reads returned HTTP 200; all four monitored services were UP/CURRENT and no incident was open. Scoped cleanup removed only the temporary project resources; the existing nine-service project and its named volumes matched before/after snapshots. |
| Complete runbooks | **Implemented.** Added `docs/runbook.md` with local startup, API/frontend smoke checks, scoped demo/test workflows, test effects, and preservation guidance; README links to it. |
| Test/CI results | **Local checks verified; hosted CI unverified.** This closeout reran the Investigation suite (72 passed) and frontend tests/build. The GitHub Actions workflow was inspected. `gh` is unavailable and the current changes are uncommitted, so a hosted run for this worktree requires explicit authorization to publish the changes. |
| Architecture diagram | **Reviewed and updated.** `docs/architecture.md` now shows bounded report proxies, scheduled recovery reads, report persistence, and optional trace evidence flow. |
| Reproducible evaluation | **Verified.** The documented Docker test profile reran and emitted the latest evaluation JSON below: 10 scenarios, 47/47 citations, fixture oracle 0/26 unsupported facts, root-cause 0/1 due to abstention, persisted POST p50 38.943 ms / p95 42.629 ms, cost unavailable. |
| Limitations | **Documented.** Root-cause ranking abstains (0/1); fixture-oracle results are not independent review; no provider cost, remote CI, production authorization, or separate database-role enforcement is verified. |
| Demo workflow | **Documented.** Runbook describes the unique-SKU order example and the existing controlled detection/trace verifiers, including their service interruption and data-retention effects. The live verifier was not rerun in this session. |

### Checks actually run in this session

- `$env:DOCKER_CONTEXT = 'desktop-linux'; .\scripts\test-investigation.ps1` — **72 passed in 4.62s**. Latest output: dataset `traceforge-investigation-phase7-v1`, 10 scenarios, 10 successful report POST runs, 9 latest snapshots; root-cause top-1 **0/1**, top-3 **0/1**, abstentions **1/1**; citations **47/47**; fixture-oracle unsupported facts **0/26**; persisted API latency p50 **38.943 ms**, p95 **42.629 ms**; metered provider cost unavailable. This supersedes earlier timing/latency figures in the Phase 7 entry below. The suite used the isolated tmpfs test profile. Its test database container was removed by the script; afterward no container remained for project `traceforge-investigation-tests`. Docker emitted a warning that the fixed `traceforge-network` already existed and was shared by the test profile; the test database remained a separate tmpfs container, no application database was used, and tests completed successfully.
- In `frontend`: `node --version` — **v24.16.0**; `npm --version` — **11.13.0**; `npm test` — **14 passed across 3 files**; `npm run build` — **passed** (`tsc --noEmit` and Vite production build).
- `docker --context desktop-linux compose config -q` — **passed**. Read-only inspection showed all **9** existing `projects` services running and healthy. The named volumes `traceforge-postgres-data`, `traceforge-tempo-data`, and `traceforge-maven-cache` remained present. No default application container was stopped or removed.
- Read-only HTTP checks: `GET /api/v1/health` — **200** (`status=ok`); `GET /api/v1/inventory/SKU-ALPHA` — **200** (`availableQuantity=0`); `GET /api/v1/detection-status` — **200**, `CURRENT`, five sources; `GET /api/v1/incidents?status=OPEN&limit=1` — **200**, empty page. No order or database record was created by these smoke checks.
- `Get-Command gh -ErrorAction SilentlyContinue` found no GitHub CLI command; therefore `gh run list --branch feature/phase4-incident-dashboard --limit 5 --json databaseId,headSha,status,conclusion,createdAt,workflowName` was skipped. Hosted CI is not claimed.
- Cold-start verification used an isolated nine-service Compose project `traceforge-p7out-3d7a8c14b2`, with a unique generated network and PostgreSQL volume, tmpfs Tempo, unique build image tags, and loopback ports 18080/18090/13000. The resolved configuration passed validation; `up --build --detach --wait --wait-timeout 600` reached 9/9 healthy. Gateway `/api/v1/health`, inventory `/api/v1/inventory/SKU-ALPHA` (quantity 12), Investigation `/readyz`, and Grafana `/api/health` returned HTTP 200. Detection status returned `CURRENT`, all four monitored services were `UP/CURRENT`, and the open incident list returned HTTP 200 with zero items. The exact disposable containers, network, temporary PostgreSQL volume, and unique build images were removed. Default project container and named-volume snapshots matched before/after. The one-off temporary manifest was removed. The default project was never stopped; the legacy database records were not read or changed.
- Java unit suites, `scripts/test-backend.ps1`, the live detection/trace verifiers, Phase 7 outage matrix, and browser workflows were **not rerun**. No Java or frontend source changed in this closeout; the isolated full-stack cold start rebuilt the Java service images and verified service readiness. Earlier Java, live detection/trace/outage, and selected desktop browser results remain historical evidence, not current-session reruns.
- `git diff --check` — **passed** after the final documentation edits; a local-link check for the updated Markdown — **passed**.
- `E:\TraceForge_Interview_Guide.md` exists outside the repository, contains all 12 requested sections, and is not tracked by this Git worktree. Its Phase 8 status and metrics were updated after local verification.
- Final Git inspection: branch `feature/phase4-incident-dashboard`, HEAD `f006bde`; **14 modified tracked files, 5 untracked files**, staged diff empty. No changes were staged, committed, or pushed.

### Closeout status

The locally achievable Phase 8 portfolio acceptance is complete: documentation/architecture review, reproducible evaluation, frontend tests/build, Compose validation, and a full isolated nine-service cold start with read-only smoke checks all passed. **Phase 8 remains open for hosted CI** because the working-tree changes are uncommitted and CI runs on push/pull request; publishing them requires explicit user authorization. Production authorization and separate PostgreSQL role enforcement remain unverified deployment limitations, not controls demonstrated by the local tests. The original default stack and named volumes were preserved; the `SKU-TEST-ORDER` warning remains untouched. Do not start another phase.

## Phase 7 evaluation and resilience — 2026-10-12

### Implementation

- Added the fixed `traceforge-investigation-phase7-v1` scenarios in `investigation/tests/test_phase7_evaluation.py`. The suite calls the real Investigation API, persists through the real repository into the isolated tmpfs PostgreSQL test database, and uses fixed in-process clients for health, Order recovery, and trace observations. Ten cases cover a healthy/no-incident request; current, stale, and missing health; a successful and an unavailable trace read; current, partial, and unavailable Order reads; an open incident contradicted by a fully compensated decline; and a resolved incident with explicit terminal compensation.
- Added measured top-1/top-3 root-cause scores, citation validity, fixture-oracle factual support rate, persisted API latency percentiles, cost availability, abstention count, and scenario status to the emitted `PHASE7_EVALUATION=` JSON. The report schema has no ranked root-cause field; the one determinate `PAYMENT_UNAVAILABLE` case is scored as an abstention (0/1 top-1 and 0/1 top-3). Unranked hypotheses/facts are not turned into predictions.
- Added explicit `InvestigationProviderUnavailable` handling: the run API returns HTTP 503 `INVESTIGATION_PROVIDER_UNAVAILABLE` without echoing provider details or persisting a report. Added tests for injected provider failure, injected PostgreSQL save failure (safe 503, no saved report, incident unchanged), repeated requests, and concurrent requests (one latest snapshot per incident).
- The focused evaluation now asserts each scenario's source-freshness map and status-appropriate uncertainty wording. This exposed a local-variable shadowing defect where stale service evidence could be described as current; renaming the probe variable preserves the report-completeness status and fixes the wording.
- Added explicit trace 503, timeout, and not-found fault tests. The evaluation caught and fixed a report wording defect: a resolved recovery now says the incident is resolved instead of referring to an open episode.
- Updated the Investigation test script to show the evaluation JSON output. The isolated test profile is still tmpfs-only; no persistent application schema or named volume is used.

### Verification completed

- Focused command: `$env:DOCKER_CONTEXT = 'desktop-linux'; docker compose --project-name traceforge-phase7-focused --profile test run --build --rm investigation-test pytest -q -s tests/test_phase7_evaluation.py` — final run **1 passed in 0.92s**. Earlier focused attempts exposed stale-health uncertainty wording and an incorrect expected phrase; the code/test defects were corrected. The test asserts `RESOLVE`, no finding, a false no-episode repository resolution, and zero incident records for the confirmed order. The dedicated test PostgreSQL container was removed after each run.
- At the Phase 7 verification point, `$env:DOCKER_CONTEXT = 'desktop-linux'; .\scripts\test-investigation.ps1` passed **72 tests in 4.40s** against the isolated tmpfs PostgreSQL service. The script's `finally` block removed its test database container; post-run inspection found no containers under the test project label. A preceding attempt in an earlier session failed during collection because the parameterized trace test lacked `import pytest`; the import was added and the suite rerun successfully. The latest Phase 8 rerun and updated metrics are recorded at the top of this task log.
- That Phase 7 output used dataset `traceforge-investigation-phase7-v1`: **10 scenarios**, **10 successful report POST runs** (including one repeat), **9 latest snapshots**, and a healthy/no-incident request that returned `404 INCIDENT_NOT_FOUND` without writing a report. Root cause top-1 **0/1**, top-3 **0/1**, abstentions **1/1**; citations **47/47 valid**; unsupported facts **0/26** under the deterministic scenario oracle; persisted API latency p50 **30.600 ms**, p95 **34.415 ms**; cost unavailable because no metered provider is configured. The factual oracle checks exact generated text against cited typed fields; it is not independent blind review. Latency used in-process upstream fixtures and is not a production SLO. These values are historical and superseded by the latest rerun above.
- Controlled tests covered bounded Order timeouts, HTTP errors, malformed/oversized and partial responses; trace unavailability, timeout, 404, malformed/oversized summaries; injected provider and database-write failures; stale/missing/contradictory evidence; repeat and concurrent writes. These tests did not stop a live application service, Collector, Tempo, or the persistent database.
- `$env:DOCKER_CONTEXT = 'desktop-linux'; docker compose config -q` — passed. `docker compose ps --all` showed all **9 default services healthy**. Post-test inspection found no container under either disposable test project label. The Compose test profile emitted a benign warning that the shared `traceforge-network` already existed; the application stack remained healthy.
- `git diff --check` — passed after the final documentation edits. No Java or frontend code changed; Java/frontend suites and browser checks were not rerun. Remote CI was not run.

### Status, known limitation, and safety

- Phase 7 evaluation, controlled fault injection, and the scoped live outage matrix are locally implemented and verified. The 0.0 root-cause scores expose a current contract limitation: deterministic-v1 makes no ranked root-cause output. No threshold was specified, and the evaluator records abstention honestly; this result must not be described as root-cause accuracy passing. Remote CI, production authorization, and separate database-role enforcement remain unverified, so broader Phase 7 sign-off remains open.
- Outage experiments used a random Compose project and synthetic `SKU-ALPHA` data. The exact project-scoped disposable PostgreSQL volume was removed after the run; existing application/observability containers and named volumes were unchanged. No `SKU-TEST-ORDER` record was touched. Nothing was staged, committed, or pushed.
- At the end of the Phase 7 session, Phase 8 had not started; the subsequent Phase 8 closeout and its measured limitations are recorded at the top of this file.

### Disposable live-outage harness prepared — 2026-10-12

- Added `scripts/phase7-outage.compose.template.yaml` and `scripts/verify-phase7-outages.ps1`. The script renders `%TEMP%\traceforge-phase7-outage.compose.yaml` from the repository template and defaults to configuration-only behavior; outage experiments require an explicit `-RunOutages`. `-CleanupProject <generated-name>` is a separately scoped recovery path for an interrupted run.
- The disposable topology contains Tempo, Collector, PostgreSQL, Inventory, Payment, Order, Investigation, and Gateway (Grafana is omitted because the matrix does not need its UI). It reuses the repository Dockerfiles/build contexts, health checks, Spring local profile, service URLs, telemetry propagation/export settings, and real recovery worker. The Order recovery delay is set to 300 seconds in this isolated harness only to leave the real detector a deterministic observation window; the worker remains enabled and runs after the Order container restarts.
- Resolved configuration uses the Compose-generated per-run network, run-tagged unique build images, one uniquely named per-run PostgreSQL test volume, tmpfs for Tempo, only the two read-only telemetry-config bind mounts, and only `127.0.0.1:18080` (Gateway) / `127.0.0.1:18090` (Investigation) host ports. The test order uses `SKU-ALPHA`; it does not connect to the application database or touch legacy `SKU-TEST-ORDER` data.
- Because Tempo data is also tmpfs-backed, the verifier does not expect an old trace to survive a Tempo container stop. It checks the outage response and optional-evidence gap, then creates a new successful order with a known `traceparent` after Tempo restarts and queries the new multi-service trace. Durable incident/source freshness persistence is checked in PostgreSQL across Investigation and PostgreSQL container restarts.
- Initial live attempts exposed and fixed two harness defects: Tempo's tmpfs needed UID/GID 10001 for its non-root runtime, and `occurrenceCount` was not a valid proxy for consecutive health probes. A subsequent attempt established that tmpfs PostgreSQL cannot persist state across a container stop. The harness now uses one unique PostgreSQL volume per random project and removes it only after verifying its Compose labels, exact expected name, and no attached containers.

### Live outage matrix completed — 2026-10-12

- Final command: `$env:DOCKER_CONTEXT = 'desktop-linux'; .\scripts\verify-phase7-outages.ps1 -RunOutages` — **PASS**, project `traceforge-p7out-9e4c24100d`. The baseline had all four health-probed services UP/CURRENT and no open incidents.
- Inventory outage: the first failed cycle `60de8ada-55e1-4527-9f0f-86d3a26d0a1d` had no incident; the next cycle `f1c185bb-8b3c-4f3d-a9ee-c66c73e08f3f` opened exactly one `SERVICE_NOT_READY` episode (`e1474a0e-fbdb-4cc2-8e4f-fbb1b6ad576e`). After restart, first UP cycle `1187bc1e-80e0-4e28-a143-5d0543297d97` kept that incident open; second UP cycle `68e8ec62-4407-4d07-8236-7f3c79f599c4` resolved the same episode.
- Order/Investigation outages: controlled incomplete compensation returned HTTP 503 with `COMPENSATION_REQUIRED` and no inventory release. The Order source became STALE without advancing `lastSuccessAt`; the same recovery incident (`60f2ebaf-f639-4873-a71e-560930ba9456`) stayed open across Order and Investigation restarts. Gateway health remained HTTP 200 while Investigation proxy reads returned HTTP 503. Once Order returned, its real recovery worker reached `FAILED` with explicit inventory release and the same incident resolved.
- PostgreSQL outage: Investigation readiness returned 503, liveness 200, and detection status 503 with `DETECTION_STORE_UNAVAILABLE`. After PostgreSQL restart, readiness recovered and the incident plus non-regressing detection source timestamp persisted in the disposable named test volume.
- Tempo outage: trace lookup returned HTTP 503; the investigation report returned HTTP 200 `PARTIAL` with `TRACE_SOURCE_UNAVAILABLE`; detection completed without changing incident state/count. After Tempo restarted, a new successful order's known trace ID was queried and contained Gateway, Order, Inventory, and Payment spans. Collector outage did not block a completed detection cycle or retrieval of the stored trace; the Collector was restored.
- Cleanup and isolation: no containers, generated network, unique images, or volume remained for project `traceforge-p7out-9e4c24100d`. Before/after Docker snapshots showed the same nine healthy default application containers and the same named volumes. No application database or `SKU-TEST-ORDER` data was modified. The script compared timestamps and queried the generated trace ID but did not print either; no full successful-run service-log bundle was saved. A post-test Docker warning about the pre-existing shared `traceforge-network` was benign; all 72 tests passed.
- Final `docker compose config -q`, harness `-PrepareOnly`, PowerShell AST parsing, and `git diff --check` passed. The Investigation suite was 72/72 at that Phase 7 closeout; Java/Gateway and frontend suites were not rerun there because their code and integration behavior were untouched. Remote CI, production authorization, and separate PostgreSQL role enforcement remained unverified. Phase 7 local outage acceptance was complete; broader sign-off remained open pending those independent checks. Phase 8 had not started at that time.

## Phase 6 evidence-backed investigation — 2026-10-12

### Implementation

- Added strict allowlisted evidence/result schemas and provenance for persisted incident/rule data, detection-store health snapshots, Order-owned recovery observations, and sanitized trace summaries retrieved only by known trace ID through the Gateway. Evidence includes source identity, observation time, freshness, and fixed signal codes; request bodies, headers, payment values/secrets, raw exceptions, and arbitrary Tempo attributes are excluded.
- Added deterministic `deterministic-v1` investigation output with distinct facts, qualified hypotheses, suggested actions, evidence citations, an explicit uncertainty statement, and typed evidence gaps. Every claim citation is checked against unique evidence IDs before persistence. No external LLM provider is selected or called; `.env.example` provider values remain blank.
- Added bounded trace collection (at most 3 known trace references, 20 spans each, 1 MiB per Gateway response), a 100-item evidence cap, and a 256 KiB persisted JSON result cap. Required-source missing/stale/unavailable cases become `INSUFFICIENT` or `PARTIAL`; an optional absent trace reference is disclosed without becoming a healthy signal. A terminal Order state contradicting an open recovery incident is disclosed as a gap; investigation never changes incident lifecycle.
- Added migration `0003_incident_investigations.sql` and a single latest-investigation JSONB row per incident in the Investigation-owned `incident_service` schema. Re-running replaces only that report. Order and trace evidence are collected via fixed, bounded service APIs; no other service schema is read.
- Added Investigation Service `POST /api/v1/incidents/{id}/investigations` to collect, validate, and persist a latest report, and `GET /api/v1/incidents/{id}/investigations/latest` to retrieve it. A missing incident and a not-yet-investigated incident return distinct 404 codes. The Gateway proxies both fixed routes with bounded response reading and a 10-second upstream read timeout.
- Added the incident-detail Investigation panel with explicit loading, not-yet-run, running, error, and result states. It displays result completeness, uncertainty, cited facts, hypotheses, actions, gaps, evidence, and per-run source freshness. It never creates sample incidents or treats failed/stale sources as healthy.

### Verification completed in this session

- `.\scripts\test-investigation.ps1` — **65 passed** against the dedicated tmpfs PostgreSQL test database. This includes evidence provenance/citations, missing/stale/partial source behavior, declined-payment compensation semantics, trace response validation/size bounds, API responses, and repository persistence through a fresh repository instance. The script's disposable test container cleanup completed.
- Pinned Gateway command `docker --context desktop-linux run --rm --network traceforge-network --mount 'type=bind,source=E:/Projects/services/api-gateway,target=/workspace' --mount 'type=volume,source=traceforge-maven-cache,target=/root/.m2' --workdir /workspace maven:3.9.16-eclipse-temurin-21 mvn -B test` — **9 tests passed, 0 failures, 0 errors, 0 skipped**.
- `npm test` — **3 files / 14 tests passed**. `npm run build` — TypeScript check and Vite production build passed.
- `docker --context desktop-linux compose config -q` — passed. A read-only Compose snapshot showed all **9 services healthy** before the Investigation restart check. Only `api-gateway` and `investigation-service` were rebuilt/recreated for the live check; no volumes were removed. A post-restart Compose health snapshot could not be obtained during closeout: Docker context/config and named-pipe access returned `Access is denied`. The live API and persisted-report reads returned HTTP 200 after restart.
- Live Gateway integration used an existing resolved `SERVICE_NOT_READY` incident: investigation POST returned HTTP 200 with `COMPLETE`, 8 collected evidence items, one optional gap, and all citations within the collected set. The latest-result GET returned the same result. Restarting only Investigation Service preserved the same investigation ID and generated timestamp; the saved result remained `COMPLETE` with 8 evidence items.
- Browser rendering: the local Overview page rendered in the in-app browser at `http://127.0.0.1:5173/#overview`, showing Gateway responding, an honest empty open-incident state, four `UP`/`CURRENT` service snapshots, and five current detection sources. Opened a real resolved `SERVICE_NOT_READY` incident and checked its saved investigation: `COMPLETE` / `deterministic-v1`, cited facts, a qualified hypothesis, recommended action, explicit uncertainty, optional no-trace gap, current source freshness, and collected evidence. No incident or business data was created. Browser console/network logs and mobile layout were not inspected. Automated component tests cover saved, empty, partial, and API-error states.
- `git diff --check` is recorded after the final documentation edits below. The full `scripts/test-backend.ps1` was not run because this change touched only the Gateway, Investigation Service, and frontend; the focused pinned Gateway suite and isolated Investigation suite were run instead. Remote CI, production authorization, and separate database-role enforcement remain unverified.

### Status and safety

- Phase 6 local implementation, automated verification, live API/restart persistence, and selected-incident browser review are complete. Remote CI, browser console/network inspection, mobile layout, production authorization, and separate database-role enforcement remain unverified. No Phase 7 or Phase 8 implementation was started.
- The live POST added/updated only an investigation snapshot for an existing resolved service incident. No order, inventory, payment, incident-lifecycle, or legacy test record was modified. The legacy `SKU-TEST-ORDER` inconsistency warning remains unchanged; do not reconcile those records or reset/delete named volumes.
- Final Git state: branch `feature/phase4-incident-dashboard`, commit `809cd8d`; 17 modified tracked files and 11 untracked Phase 6 files, with an empty staged diff. No files were staged, committed, or pushed.

## Phase 5 dashboard: service health and trace evidence — 2026-10-12

### Implementation

- Extended `GET /api/v1/detection-status` with persisted probe snapshots for the four fixed services. Each reports `UP`/`DOWN`/`TIMEOUT`/`UNKNOWN`, observation time, source freshness, and whether a service-health incident is open. Missing observations remain `UNKNOWN` + `UNAVAILABLE`.
- Added `GET /api/v1/traces/{traceId}` through the Gateway. It validates lowercase 32-hex IDs, uses bounded timeouts, caps Tempo input at 1 MiB and output at 250 spans, and returns only allowlisted span fields. Raw Tempo attributes/events and request, exception, or payment content are not forwarded.
- Added dashboard service-health and on-demand trace-summary views. Added ADR 0007 and updated architecture/security/roadmap/README/handoff documentation. No schema migration or business-table change was needed.

### Verification completed

- Docker diagnosis: `docker context show` returned `default`; `docker info` and `docker compose ps -a` failed because `default` targets `npipe:////./pipe/docker_engine`, which denied access. `docker context ls` showed `desktop-linux` at `npipe:////./pipe/dockerDesktopLinuxEngine`; `docker --context desktop-linux info` succeeded. Commands were run with the per-process `$env:DOCKER_CONTEXT = 'desktop-linux'`; no global context setting was changed.
- $env:DOCKER_CONTEXT = 'desktop-linux'; `.\scripts\test-investigation.ps1` — first run: 53 passed, 1 failed because a test reused a monkeypatched frozen clock. The test now calls the saved original repository method for its advanced-time assertion, preserving the stale assertion. Final rerun: **54 passed** against the isolated tmpfs PostgreSQL test database; its disposable container was removed.
- Pinned Gateway tests ran `docker run --rm --network traceforge-network --mount "type=bind,source=E:/Projects/services/api-gateway,target=/workspace" --mount "type=volume,source=traceforge-maven-cache,target=/root/.m2" --workdir /workspace maven:3.9.16-eclipse-temurin-21 mvn -B test`. The first compile found a missing `IOException` import; after fixing it, Spring context setup found the production `TempoClient` constructor was ambiguous with its test constructor. Marked the production constructor `@Autowired`; final result **8 tests passed, 0 failures/errors/skips**.
- `$env:DOCKER_CONTEXT = 'desktop-linux'; docker compose config -q` — passed. Then `docker compose build api-gateway investigation-service` and `docker compose up -d --no-deps --force-recreate --wait --wait-timeout 120 api-gateway investigation-service` built/recreated only the changed services; running container image IDs matched their new tags. `docker compose ps` showed all 9 services healthy.
- `.\scripts\verify-detection.ps1` with `$env:DOCKER_CONTEXT = 'desktop-linux'` — **passed, exit 0**. It confirmed success and fully compensated decline create no incidents; stalled compensation opens one episode; failed/stale sources do not resolve; explicit terminal Order state plus completed compensation resolves; probe incidents open after failures and resolve after healthy probes; persisted freshness survives Investigation restart; and detection completes with Collector stopped. Its `finally` restored Order, Inventory, Collector, and Investigation and removed scoped generated business rows/order incidents. The verifier intentionally leaves resolved service-health incident history from its controlled outages.
- Live rebuilt API checks: detection status returned 4 services, all `UP`/`CURRENT`, with no open service incidents. A read-only Inventory GET with caller trace ID `f6b51cb4545d465ab730f6e1681efdc9` was later queried through the Gateway and returned **4 spans** across `api-gateway` and `inventory-service`; response size was 1,268 bytes and only allowed fields were present. The bounded polling initially found a partial trace and then the full trace on the next query. After the detection verifier, the resolved history page returned 23 items and one had a real trace reference.
- Trace route cases: valid trace **200**; malformed ID **400**; nonexistent trace **404**; with Tempo stopped, valid ID **503**. Tempo was restored and `/ready` returned **200**. The live detection verifier completed cycles while Collector was stopped; Tempo is not a detector input by design.
- Final read-only check after recovery: all **9** Compose containers were `running` and `healthy`; `GET /api/v1/detection-status` returned `CURRENT` with 4 services and 5 sources, all service probes `UP`/`CURRENT`; open incident count was 0. The synthetic detection run left resolved `SERVICE_NOT_READY` history from the actual temporary service stops. No named volume was removed, no `SKU-TEST-ORDER` data was read-modified or reconciled, and no files were staged/committed/pushed.
- Frontend `npm test` (**2 files / 11 tests**) and `npm run build` had passed during the preceding Phase 5 implementation session; they were not rerun here because no frontend source changed. `git diff --check` passed after the final documentation update.

### Remaining acceptance and next action

- Four supplied desktop screenshots manually document the per-service health indicators and probe freshness; separate detection-source freshness; the honest empty-open-incidents wording that an empty result does not establish every source is healthy; real resolved `SERVICE_NOT_READY` history; a resolved detail with real `HEALTH_PROBE` / `CONNECT_FAILED` evidence; and the trace-evidence section when no trace references are returned. This verifies those visible desktop workflows only. It does not verify every interaction, browser network request, mobile layout, or exhaustive browser behavior. An earlier browser-automation attempt was blocked by the local URL security policy; the screenshots are the available visual evidence.
- The full `scripts/test-backend.ps1` was not rerun: the changed backend components received their isolated/full module suites and live detection verifier; the script would rebuild the full stack and run unrelated service/saga/trace restart suites. Remote CI, production authorization, and database-role enforcement remain unverified.
- Preserve the existing legacy warning: `SKU-TEST-ORDER` has 94 available units but 113 reservation rows representing 139 unreleased units. Do not reconcile it. Phase 5 is implemented and locally verified for its documented scope; remote CI, production authorization, and separate database-role enforcement remain unverified. Phase 6 evidence-backed investigation is next; do not implement Phase 7 or 8 in that work unless the roadmap explicitly requires a small dependency.
- This documentation-only closeout recorded the supplied screenshot evidence and prepared the Phase 6 prompt. Tests, builds, browser checks, Compose, and integration verification were not rerun; `git diff --check` was run after the documentation edits and passed.

## Phase 4 frontend incident dashboard — 2026-10-12

### Implementation

- Connected the Overview to the real gateway health, incident list/detail, and detection-status APIs. Added open incidents, resolved-history filtering, opaque-cursor pagination, selected evidence details, and a separate per-source freshness panel.
- Added explicit loading, empty, API-error, stale, partial, unavailable, and not-run states. Empty results and missing/stale sources are not presented as confirmed healthy. No demonstration incidents or synthetic success states were added.
- Added runtime response-shape validation and safe API error messages. The dashboard only displays trace identifiers when the API returns them.
- No backend, database, Compose, telemetry, or legacy `SKU-TEST-ORDER` data was changed.

### Checks run in this session

- `cd frontend; npm test` — **passed: 2 test files, 9 tests**.
- `cd frontend; npm run build` — **passed** (`tsc --noEmit` and Vite production build).
- Started the Vite development server and queried its `/api` proxy with `Invoke-WebRequest`: gateway health returned **HTTP 200**; `GET /api/v1/incidents?status=OPEN&limit=25` returned **HTTP 200**, zero open items, and `CURRENT` detection status; `GET /api/v1/detection-status` returned **HTTP 200**, `CURRENT`, and five sources. The Vite server started by this check was stopped afterward.
- `git diff --check` — **passed** before the documentation update; rerun after the final edits below.
- Browser rendering — **verified on desktop** at `http://127.0.0.1:5173/` in the Codex in-app browser. The Overview showed gateway health, a `CURRENT` completed detection cycle with five `CURRENT` sources, and the honest empty-open-incidents message. Resolved history loaded existing records, and a real resolved `SERVICE_NOT_READY` incident for `api-gateway` displayed its two `CONNECT_FAILED` evidence observations. No incident data was fabricated or changed.
- Browser checks — viewport 1280×720; document width 1265 px and no horizontal overflow. Browser console error/warning query returned no entries. The browser automation exposed no dedicated network panel; successful live API-backed content was visible, and direct HTTP/Vite-proxy checks above returned HTTP 200. Mobile layout and exhaustive browser workflows remain unverified.
- `docker compose ps` — **blocked** because this session was denied access to the Docker named pipe. Direct gateway/Vite-proxy HTTP checks succeeded, but Compose health was not freshly verified.
- The previously reported 53 Investigation tests, 37 Java tests, restart checks, and Tempo/detection integration checks were **not rerun** in this frontend session. Remote CI was **not run or verified**. An `origin` remote is configured, but this branch has no upstream.

### Remaining checks

- Browser rendering closeout is complete for the desktop Overview, empty open state, freshness panel, resolved history, and one real detail view. Do not infer mobile or exhaustive workflow coverage from this check.
- Compose health was not freshly verified because `docker compose ps` was denied Docker named-pipe access. Remote CI, production authentication/authorization, and separate PostgreSQL role enforcement remain unverified.
- Preserve the legacy `SKU-TEST-ORDER` inconsistency warning; no database records or named volumes were touched.

## Phase 4 final backend integration — 2026-10-10

### Implementation completed

- Added explicit bounded terminal observations in Order Service for up to 100 unique order IDs already attached to open recovery incidents. The detector only resolves from an explicit terminal Order result with compensation complete; `missingOrderIds`, failed requests, and stale sources are not resolution signals.
- Activated the single-cycle scheduler with PostgreSQL advisory-lock serialization. Detection cycles, service health streaks, and per-source attempted/last-success freshness persist in the `incident_service` schema across Investigation restarts.
- Added bounded, read-only Investigation APIs for incident list/detail and detection status, proxied through fixed Gateway routes. Internal Investigation and Order endpoints remain private to the Compose network.
- Added `scripts/verify-detection.ps1` to verify healthy and compensated business outcomes, compensation incident opening/deduplication/resolution, source failure non-resolution, Investigation restart persistence, two-probe service incident open/resolve, and detection continuing with the optional Collector stopped. Its `finally` independently attempts to restore every service it may stop and removes only order incidents linked to that run's generated idempotency keys.
- No frontend incident UI was started. The `SKU-TEST-ORDER` legacy inconsistency warning remains; its records were not readjusted or reconciled, and no Docker volumes were deleted.

### Validation and actual results

- `.\scripts\test-investigation.ps1` — **passed: 53 tests** against the isolated tmpfs PostgreSQL test service. Cleanup completed with exit code 0.
- `.\scripts\test-backend.ps1` — the first resumed run failed in the new live verifier because PowerShell converted JSON UTC timestamps to local wall time; the detector itself continued to persist `COMPLETE` cycles and `CURRENT` source status. Fixed timestamp comparisons and strengthened restart/source-failure assertions. The final rerun **passed with exit code 0** using `maven:3.9.16-eclipse-temurin-21`: Gateway 3, Inventory 8, Payment 4, Order 22 (**37 tests; 0 failures, 0 errors, 0 skipped**), saga recovery/restart assertions, Tempo trace assertions, and deterministic detection assertions.
- The final live verifier observed: confirmed and fully compensated declined orders created no incident; an incomplete compensation opened one episode and repeated observations updated the same incident; Order unavailability did not resolve that incident and retained persisted last-success freshness; the same incident survived Investigation restart; two UP probes resolved the Order health incident; explicit terminal state plus released inventory resolved the recovery incident; two failed/timeout probes opened an Inventory health incident and two UP probes resolved it; detection completed while Collector was stopped. Collector, Order, and Inventory were restored healthy.
- Tempo was queried for actual exported traces: success `14654c73679a45bf838ee72a26ffb933` shared the caller-supplied trace ID and parent span across Gateway, Order, Inventory, and Payment; unknown SKU `91b5171abf7e4826b446516b2f0df729` had HTTP 404 and `UNKNOWN_SKU`; payment decline `de6e500a7d0b47b68cf2ae91902991b6` had an `ERROR` payment span and compensation; outage/recovery `d451343aa189419fb49a00e3d62d9753` had a separate recovery trace linked to the originating order span. Collector-outage business behavior still returned HTTP 402 with inventory released.
- `docker compose config -q` — passed after documentation updates. Final `docker compose ps` showed all **9** project services healthy. `git diff --check` passed after the final documentation update.
- No frontend tests/build were rerun in this backend-only stage because no frontend files changed. The Phase 3 Chrome Overview spot-check remains the only browser evidence at this checkpoint; it was not repeated and was not exhaustive. Remote CI remained unverified because no Git remote was configured at that time.
- Two earlier verifier attempts left resolved incidents associated with their own generated orders. Each exact row was checked by incident ID, rule, source order ID, scope, and resolved status before removal. The verifier now cleans only order incidents tied to the current run's generated order keys. Resolved `SERVICE_NOT_READY` episodes from controlled service outages remain as incident history; they were not deleted because they share service-level fingerprints with possible real observations.

### Remaining gaps / next work

- At this 2026-10-10 backend-only checkpoint, Phase 4 detection was locally implemented and verified; the frontend incident view and browser workflow coverage were the next milestone. The 2026-10-12 frontend implementation and its remaining browser limitation are recorded at the top of this task log.
- Remote CI, production authentication/authorization and separate database roles remain unverified/out of scope. The `incident_service` schema shares the local PostgreSQL credentials and is an ownership boundary, not a privilege boundary.
- Preserve the legacy `SKU-TEST-ORDER` data warning below; no legacy stock or reservation rows were changed.

## Historical Phase 4 combined Stage 2+3 implementation record — 2026-10-10 (superseded by final integration above)

### Changes

- Added the Python 3.12/FastAPI `investigation-service` to the default Compose stack. It is internal-only (no published host port), applies versioned migrations to its owned `incident_service` schema, and exposes only `/healthz` and database-backed `/readyz`.
- Added strict typed models, bounded fixed-target readiness probes for Gateway/Order/Inventory/Payment, and a bounded keyset client for Order `GET /internal/v1/orders/attention`. Probe calls have 0.5-second connect and 2-second total timeouts, health response bodies are capped at 8 KiB, Order pages at 1 MiB, and collection stops at 500 pages / 50,000 cases. Partial Order reads are not passed to rules as complete empty results. Freshness is reported in the in-memory cycle result but is not yet persisted or exposed.
- Added deterministic `SERVICE_NOT_READY` and `ORDER_RECOVERY_STALLED` evaluators and PostgreSQL persistence for incidents and health streak state. Health opens after two fresh ordered DOWN/TIMEOUT observations and resolves after two fresh UP observations; unknown, stale, future, or replayed observations do not advance streaks. Order findings cover overdue recovery, manual review/retry exhaustion, and explicit incomplete compensation. Fingerprints deduplicate open episodes; evidence is structured and capped at 20 references. Fully compensated declines and confirmed orders are not findings.
- Added an isolated Compose `test` profile with a separate test Postgres container backed only by tmpfs, a fixture guard for the exact disposable database identity, `scripts/test-investigation.ps1`, and a CI workflow step. No legacy test database, `SKU-TEST-ORDER`, or application volume was used or cleaned.
- This is engine and persistence code, not an activated detection service: `run_once()` has no scheduler or trigger and no incident read API/UI exists. The Order attention endpoint returns active cases only. Although the rule evaluator accepts explicit terminal state for resolution, the current source cannot provide terminal snapshots after a case leaves attention, so order incident resolution is not wired and disappearance is never treated as resolution.

### Validation and actual results

- `python -m compileall -q investigation/traceforge_investigation investigation/tests` — passed.
- `docker compose config -q` — passed.
- `.\scripts\test-investigation.ps1` — **passed: 45 tests**, using the separate tmpfs PostgreSQL service. The script's cleanup completed successfully.
- `docker compose up --build -d --wait investigation-service` — passed. `docker compose ps investigation-service` showed healthy. Live in-container `GET /healthz` and `GET /readyz` both returned HTTP 200; a read-only database query confirmed migration `0001` was applied.
- `.\scripts\test-backend.ps1` — passed: Gateway 1, Inventory 8, Payment 4, Order 20 (**33 tests, 0 failures, 0 errors, 0 skipped**); saga restart/recovery and Tempo checks passed. All **9** Compose services were healthy during the run. The actual Tempo checks verified success (`c616652094374c03818f17f8090d0abb`), unknown SKU (`1f25acfebcdc4dbf9a4d4bb9d6590735`), payment decline with ERROR span/compensation (`371b4b28b162400da9020a1148f64202`), and outage/recovery (`5cdfe229ff574822a8bf09bb8ce3fbb9`), with recovery linked to the originating order span. Collector-outage behavior preserved the HTTP 402 decline and inventory release, then the Collector was restored.
- `npm test` — passed: 1 file, 2 tests. `npm run build` — passed. The test runner used repo-local ignored temp storage after default Windows sandbox temp failed with `EPERM`.
- Final post-documentation results: `git diff --check` and `docker compose config -q` passed.
- A read-only post-documentation `docker compose ps --all` showed all 9 services healthy; in-container `GET /healthz` and `GET /readyz` each returned HTTP 200.
- Remote CI remained unverified at this earlier checkpoint, when no Git remote was configured. Browser rendering was not exercised in that stage; only the earlier documented Chrome Overview spot-check was available and was not exhaustive.

### Remaining gaps / next milestone

- Add a bounded Order signal that can report explicit terminal states for previously open recovery cases; do not resolve based on missing rows from the attention endpoint.
- Add a controlled scheduler/trigger, durable/exposed source freshness, and an internal incident read API, then verify complete detection and recovery workflows end to end.
- The incident schema shares the existing local Postgres database user and is not a database privilege boundary. Remote CI, production authorization/roles, and exhaustive browser workflows remain unverified.
- Preserve the existing legacy-data warning below: `SKU-TEST-ORDER` has inconsistent stock/reservation records. No rows or Docker volumes were modified for this stage.

## Historical Phase 4 Stage 1 — incident contract and Order attention query — 2026-10-10

### Changes

- Added [ADR 0006](docs/adr/0006-deterministic-incident-detection.md) and a Phase 4 contract section in `docs/architecture.md`. The planned investigation service owns health/recovery observation freshness, deterministic rules, incident persistence/deduplication, and incident read APIs; it will write only to `incident_service`. `SERVICE_NOT_READY` and `ORDER_RECOVERY_STALLED` are the initial rules. Tempo is optional evidence, and missing/stale telemetry is not a healthy observation.
- Added the private Order Service `GET /internal/v1/orders/attention` read endpoint. It returns active orders with a stored recovery error, pending compensation, or a due recovery deadline. The page defaults to 50 and is capped at 100, ordered by `(created_at, id)`, and uses paired `afterCreatedAt` / `afterId` keyset parameters. Items expose only order/workflow/recovery fields, timestamps, and nullable `originTraceId`; no SKU, quantity, reservation/payment IDs, or request/exception data is returned. The service port remains private to the Compose network and no Gateway route was added.
- Added transaction-scoped integration fixtures covering empty pages, recovery inclusion, exclusion of terminal success and fully compensated decline, cursor ordering/pagination, page-size validation, allowlisted response fields, and nullable trace serialization. The tests did not use or clean up `SKU-TEST-ORDER`; its existing inconsistency warning above remains unchanged.
- At the end of Stage 1, Stage 2 had not started. The later combined Stage 2+3 entry above records the implementation; there is still no scheduler, incident API, or incident UI.

### Validation and actual results

- Focused Order attention tests ran in a one-shot `maven:3.9.16-eclipse-temurin-21` container with the Order Service mounted at `/workspace`, the Maven cache volume mounted at `/root/.m2`, and database environment resolved from Compose; Maven invocation `mvn -B -Dtest=OrderAttentionControllerTest test` — **passed: 6 tests, 0 failures, 0 errors, 0 skipped**. The fixtures rolled back and credentials were not printed.
- `.\scripts\test-backend.ps1` — **passed on the final rerun** using Docker JDK 21/Maven 3.9.16: Gateway 1, Inventory 8, Payment 4, and Order 20 (**33 total; 0 failures, 0 errors, 0 skipped**). Saga restart/recovery checks passed. The Tempo script queried and verified the successful order, unknown-SKU, payment-decline/compensation, outage/recovery traces, and Collector-outage business behavior. The script recreated application/trace containers; PostgreSQL remained on its existing named volume and no volumes were removed.
- `docker compose config -q` — passed before the full backend script; the script also validated the Compose configuration.
- `docker compose exec -T order-service wget -qO- 'http://127.0.0.1:8082/internal/v1/orders/attention?limit=1'` — **HTTP 200**, valid page with `limit=1`, zero returned items, and no next cursor at the time of the live read. Only the response shape/count was displayed.
- `git diff --check` — passed after the final documentation update (Git emitted existing LF-to-CRLF working-copy warnings only).
- No frontend tests were run because this stage makes no frontend changes. Browser rendering and remote CI were not exercised by this stage; remote CI remains unverified as previously recorded.

### Next step

At Stage 1 closeout, the next step was the investigation service and rules. That work is recorded in the newer combined Stage 2+3 entry above. Continue with the outstanding gaps listed there; do not treat the current code as scheduled or end-to-end incident detection.

## Phase 3 review remediation — 2026-10-10

### Changes

- Fixed `PaymentController` to compare `PaymentStatus.DECLINED` as an enum. The payment response remains uppercase (`AUTHORIZED` / `DECLINED`) with the same HTTP status and body. `scripts/verify-traces.ps1` now asserts the exported Tempo `payment.authorize` span status is `OK` for authorization and `ERROR` for decline; it does not infer status from the `payment.outcome` attribute.
- Replaced shared mutable `SKU-TEST-ORDER` / `SKU-TEST-TINY` use in Inventory and Order integration tests with per-test SKUs. Order and Payment tests now use run-scoped idempotency keys and remove only records created in that scope. Cleanup checks reconcile available stock plus active reservations to the fixture's initial quantity, then assert scoped reservations, orders, payments, and SKU rows were removed.
- Updated `verify-saga-recovery.ps1` and `verify-traces.ps1` to create unique database-backed test SKUs, track their order keys, and clean only those exact rows in `finally` blocks. The shared `TraceForgeTestData.ps1` helper validates test key/SKU formats and fails if scoped cleanup leaves rows behind.
- Moved the Collector stop command inside the outage test's `try` block. Its `finally` always attempts to start and wait for the Collector, including when `docker compose stop` fails after partially stopping it.
- Updated ADR 0005 to record accepted local tracing behavior; the later closeout update below records the Chrome spot-check and the remaining remote CI blocker.

### Existing persistent data observed and preserved

A read-only query against the existing Compose PostgreSQL volume found historical records from the former shared-fixture test setup. They were not deleted or reset:

- `SKU-TEST-ORDER` reports 94 available units, with 113 reservation rows and 139 units in unreleased reservations. That legacy fixture is inconsistent with its original 100-unit seed because earlier test runs reset its quantity while retaining reservation rows.
- `SKU-TEST-TINY` reports 1 available unit and no reservation rows.
- The database has 72 orders with the historical `order-test-` key prefix (46 `CONFIRMED`, 26 `FAILED`), 34 old restart/trace-script orders (19 `CONFIRMED`, 15 `FAILED`), 14 old `payment-test-` attempts, and 60 payment attempts linked to those 72 `order-test-` orders.
- The new tests and scripts use unique fixtures and remove only their current run's rows, so they do not change the legacy shared fixture or those existing order/payment records. No volumes or application data were reset.

### Validation and results

- `.\scripts\test-backend.ps1` — **passed twice serially** with the pinned Docker Maven/JDK image `maven:3.9.16-eclipse-temurin-21`. Each run reported Gateway 1, Inventory 8, Payment 4, and Order 14 tests: **27 passed, 0 failures, 0 errors, 0 skipped**. The second run included the cleanup assertions and confirmed fixture stock/active-reservation reconciliation and removal of each test's own rows.
- Both runs passed the script's saga restart checks: scheduled recovery after Order/Inventory/Payment restarts, persisted payment authorization recovery after Payment restart, and compensation across Order/Inventory restarts.
- Both runs passed `scripts/verify-traces.ps1` against actual Tempo-exported traces. On the latest run:
  - Success trace `cd21f3371b81442f9923b357750a6d4f` contained Gateway, Order, Inventory, and Payment under the caller `traceparent`; the exported Payment authorization span status was `OK`.
  - Unknown-SKU trace `d87df1f4756347bdaf362db739f64bc2` contained HTTP 404 and `UNKNOWN_SKU` evidence.
  - Payment-decline trace `884d57db4fc94952a7a5b8acc8841dc9` contained an exported Payment authorization span with `ERROR`, plus inventory release/compensation evidence; the workflow returned HTTP 402.
  - Payment-outage trace `11140984119a4d8fbf9f1054d36cf4e9` remained distinct from the scheduled recovery trace, whose worker span linked to the originating order span.
  - While Collector was stopped, a payment decline still returned HTTP 402 and confirmed inventory release; the `finally` restoration returned Collector to healthy.
- The first retry briefly overlapped an earlier Compose test runner and two Order tests saw downstream HTTP 503s while services were being recreated. After that runner exited, two serial full runs passed; no assertions or expected statuses were weakened.
- `docker compose config -q` — passed. Final `docker compose ps` showed all eight services healthy. Live `GET http://localhost:8080/api/v1/health` returned HTTP 200 with `status=ok` and `service=api-gateway`.
- Frontend `npm test` — passed, 1 file / 2 tests. `npm run build` — passed (`tsc --noEmit` and Vite production build).
- `git diff --check` — passed with existing LF-to-CRLF warnings. PowerShell AST parsing passed for `TraceForgeTestData.ps1`, `verify-traces.ps1`, and `verify-saga-recovery.ps1`.
- No files were staged or committed; no host software or system-wide settings were changed. At this verification stage, browser rendering and remote CI remained unverified; see the later closeout update below.

## Distributed observability milestone — current session, 2026-10-10

### Final verification update — build fix and runtime evidence

- Fixed the reported Payment Service compiler error in `PaymentController`: `PaymentStatus` is an enum, so the trace attribute now uses `attempt.status().name().toLowerCase(Locale.ROOT)`. This only converts the tracing outcome attribute; Spring still serializes the API enum as uppercase `AUTHORIZED` / `DECLINED`, as the existing payment tests require. A scan of all service code found no other enum-to-string conversion using case methods directly on an enum.
- The first Docker rebuild reached Tempo and exposed an incompatible legacy `compactor` configuration field. Updated `observability/tempo.yaml` to Tempo 3's backend scheduler/worker compaction configuration; the rebuilt Tempo container became healthy and stored queryable traces.
- The first trace assertion exposed that Tempo's OTLP JSON API encodes binary trace/span IDs as Base64 while the caller's W3C IDs are hexadecimal. `scripts/verify-traces.ps1` now normalizes Tempo IDs before asserting trace IDs, parent IDs, and recovery links, and checks all returned spans belong to the requested trace.
- A subsequent full run correctly rejected the Collector-outage test order with HTTP 409 because repeated development runs had consumed `SKU-ALPHA` in the persistent database. Updated the trace verifier's ordinary order scenarios to use the seeded `SKU-TEST-ORDER` fixture, making repeated checks independent of the depleted demo SKU. The unknown-SKU case remains intentionally unknown.
- No files were staged and no commit was created. No software was installed and no system-wide settings were changed.

#### Commands and actual results

- `.\scripts\test-backend.ps1` — **passed on the final rerun**. It built and started the complete Compose stack with `maven:3.9.16-eclipse-temurin-21` / JDK 21. Maven results: API Gateway 1, Inventory 8, Payment 4, Order 14 (including 2 tracing unit tests); **27 tests total, 0 failures, 0 errors, 0 skipped**.
- The same script's live saga restart checks all passed: scheduled order recovery after Order/Inventory/Payment restarts; persisted reservation and idempotent recovery; persisted authorization after Payment restart and timeout; and compensation intent/release across Order and Inventory restarts.
- The final `scripts/verify-traces.ps1` run, invoked by `test-backend.ps1`, **passed all Tempo-exported trace assertions**. It bounded polling and retrieved traces by ID from Tempo; results:
  - Confirmed order: caller trace `6ab26892f10e4d5980d949136906fa3f`; Gateway, Order, Inventory, and Payment spans shared that trace, and the Gateway server span retained the supplied caller parent span ID.
  - Unknown SKU: `ce0b9beb9b70426caa76892b08d94a2e`; HTTP 404, `UNKNOWN_SKU`, and Inventory HTTP 404 were present.
  - Payment decline: `ce69bb3f6a5e4ff9a5fe680bff268df0`; HTTP 402, `PAYMENT_DECLINED`, payment decline, and inventory release spans were verified.
  - Payment outage: `581141beddba43208ae002c42c780bab`; HTTP 503 retained `INVENTORY_RESERVED`, the scheduled recovery later confirmed the order, and Tempo returned a distinct recovery trace containing a link to the originating order span.
  - With the Collector stopped, a controlled payment decline still returned HTTP 402 with `inventoryReleased: true`; the Collector was restored healthy in the script's `finally` path.
- `GET http://localhost:8080/api/v1/health` — **HTTP 200**, body `{"status":"ok","service":"api-gateway","timestamp":"2026-10-10T10:42:06.622367741Z"}`.
- `docker compose ps` after verification — **all eight services healthy**: API Gateway, Inventory, Order, Payment, PostgreSQL, Tempo, Grafana, and OpenTelemetry Collector.
- `docker compose config -q` — **passed** after the final run.
- From `frontend`: `npm run build` — **passed** (`tsc --noEmit` and Vite production build). First `npm test` attempt failed before executing tests because Windows sandbox temp-directory rename returned `EPERM`; reran with `$localTemp = Join-Path (Get-Location).Path '.codex-tmp'; New-Item -ItemType Directory -Force -Path $localTemp | Out-Null; $env:TEMP = $localTemp; $env:TMP = $localTemp; $env:TMPDIR = $localTemp; npm test`, and Vitest passed **1 file / 2 tests**.
- `git diff --check` — **passed** (Git reported only its existing LF-to-CRLF conversion warnings for modified files).
- At this stage, browser rendering and interactive browser workflow were still unverified; see the later closeout update below. Remote CI execution remained unverified.

### Baseline and independent review

- `git status --short --branch` was clean on `master` before edits; HEAD was verified as `e30a826 chore: establish TraceForge foundation`. No commits, resets, or staging were performed.
- Reviewed the master specification, README, prior task log, roadmap, architecture/security docs, current Compose services, four service POMs/Dockerfiles, HTTP clients/controllers, recovery code, migrations, and existing tests. Current Spring Boot version is 4.1.1 and Java release is 21 across all four services. Existing container builds use `maven:3.9.16-eclipse-temurin-21` and runtime `eclipse-temurin:21-jre-alpine`.
- The previous task-log entry records 25 backend tests and successful saga restart checks. At the point this section was first written, Docker was unavailable; the final verification and subsequent fixes are recorded below.
- Official image source review showed the upstream Collector runtime is `scratch` and Tempo is distroless. The Compose shell/`wget` checks previously configured for those images would not run. Added small Alpine wrappers around the pinned upstream binaries so the checks can call Collector's configured health extension and Tempo's `/ready` endpoint.

### Work in this session

- Added a pinned OpenTelemetry Java agent (`2.30.0`) to the four service images, with consistent OTLP/HTTP configuration in Compose. The Order, Inventory, and Payment services add aligned OTel API (`1.64.0`) custom business spans; automatic agent instrumentation owns HTTP spans and propagation.
- Added Order create/recovery spans and private persisted trace/span IDs so scheduled recovery can start a new trace linked to the originating order span. Inventory reservation/release and payment authorization spans capture operation outcomes and safe identifiers/statuses. No metric/log exporters or high-cardinality metric labels were added.
- Added a traces-only Collector → Tempo pipeline, local Grafana Tempo data source, Tempo named storage volume, loopback-only UI/query ports, non-root Alpine health-probe wrappers, and `scripts/verify-traces.ps1`. The integration script uses unique caller-provided `traceparent` IDs, queries Tempo with bounded polling, and asserts confirmed, inventory rejection, payment decline/compensation, service outage, caller trace ID, and linked scheduled recovery evidence. It also stops Collector around a payment-decline request, asserts that HTTP 402 and inventory compensation remain the business result, and restores Collector in a `finally` block.
- Added a focused `OrderTracingTest`, CI invocation, architecture/security/ADR/README/roadmap updates. At the point this section was first written, Phase 3 remained pending; the final Tempo results are recorded below.

### Commands and actual results

### Initial verification attempt while Docker was unavailable (historical; superseded by the final update above)

- `docker compose config -q` — **passed** after the observability Compose changes.
- `frontend`: `npm test` — **passed**, 1 test file / 2 tests. The temp directory was directed to the repository-local `.codex-tmp` because the default sandbox temp path had produced an EPERM on an earlier baseline run.
- `frontend`: `npm run build` — **passed**, `tsc --noEmit` and Vite production build.
- Parse all service `pom.xml` files as XML — **passed**, four POMs.
- PowerShell AST parse of `scripts/verify-traces.ps1` — **passed**.
- `git diff --check` — **passed** (Git emitted only line-ending conversion warnings).
- `./scripts/test-backend.ps1` — **blocked before building or running tests**. Docker returned `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine ... The system cannot find the file specified.` The Docker Desktop executable was launched and processes appeared, but the engine pipe remained absent, including for a read-only elevated `docker info` check. No host software was installed and no system settings were changed.
- Live `GET http://127.0.0.1:8080/api/v1/health` and `GET http://127.0.0.1:3200/ready` — **not verified**; elevated read-only requests were actively refused on both ports. No HTTP status/body was returned.
- `scripts/verify-traces.ps1`, the new Java tracing unit tests, backend compilation, Collector/Tempo image builds, and full-stack health checks — **not run** because Docker was unavailable. No successful or failure trace ID is available, and no end-to-end propagation claim is made.

### Initial blocker and follow-up at that point (resolved below)

At that point the follow-up was to restore Docker access, rerun the backend suites and trace verifier, and record actual trace IDs. Docker access was restored and that work completed in the final verification update above. No files were staged or committed.

## Previous payment-saga milestone record — 2026-10-10

The existing gateway/order/inventory application was reviewed before implementation against the master specification, repository instructions, README, task log, roadmap, architecture, migrations, Dockerfiles, Compose setup, and service tests. The earlier order path persisted `PENDING_INVENTORY`, reserved inventory by order UUID, and stored `CONFIRMED` only after Inventory responded. There was no client order idempotency key, release operation, Payment Service, or recovery worker; writes were independent local transactions. The previous baseline suites were also rerun before changes: Gateway 1, Inventory 6, and Order 6 tests passed.

Implemented a separate Payment Service with its own Flyway-managed schema and deterministic simulator. The Order Service now persists a required idempotency key/payload and advances through explicit compare-and-set states. Inventory reservations and releases are transactional and idempotent; payment authorization/decline is durable and idempotent. A scheduled Order Service worker retries due states with 15-second minimum spacing and stops automatic retries after ten failures. Manual recovery is local-profile-only.

### Final verification

- `scripts/test-backend.ps1` — passed in Docker using `maven:3.9.16-eclipse-temurin-21`; it rebuilt and started the complete Compose stack, then ran the suites on the Compose network against PostgreSQL and real Inventory/Payment HTTP services.
  - Gateway: 1 test passed.
  - Inventory: 8 tests passed.
  - Payment: 4 tests passed.
  - Order: 12 integration tests passed.
  - Total: 25 tests, 0 failures/errors/skips.
- The first expanded backend run caught one invalid test fixture: its generated unknown SKU contained lowercase hex and correctly received HTTP 400. The fixture was corrected to uppercase; the final complete run passed.
- The script's live restart/recovery assertions all passed:
  - The scheduled worker automatically resumed an `INVENTORY_RESERVED` order after Order, Inventory, and Payment service restarts; it reached `CONFIRMED`, and stock was decremented once.
  - A repeated manual recovery of that terminal order did not change its payment authorization or stock.
  - A payment authorization committed before its response timeout remained available after Payment Service restart; recovery returned the same authorization ID and did not reserve stock twice.
  - `COMPENSATION_REQUIRED` survived Order and Inventory restarts; recovery released stock once, moved to terminal `FAILED`, and repeated recovery did not change stock.
- Final live gateway `GET /api/v1/health` — HTTP 200, body `{"status":"ok","service":"api-gateway","timestamp":"2026-10-10T08:32:23.537236410Z"}`.
- Final live gateway order create/read after the latest image rebuild — `POST /api/v1/orders` returned HTTP 201 with `CONFIRMED`, order ID `9cc212fb-c7ca-41f2-99ab-f0ab8d6b1fac`, reservation ID `09cc2081-8e51-40dd-9098-f7161d13278f`, and authorization ID `cc7d894d-813f-4026-a369-a88211340e30`; subsequent GET returned HTTP 200 for the same order.
- Frontend `npm test` — passed: 1 file, 2 tests.
- Frontend `npm run build` — passed (`tsc --noEmit` and Vite production build).
- `docker compose config -q` — passed. The Compose stack reported all five services healthy during backend verification.
- No host software was installed or system-wide settings changed. Backend tests use the pinned Docker toolchain; no Maven wrapper or host Maven is required.
- No files were staged and no commit was created.

## Implemented behavior

- `POST /api/v1/orders` requires `Idempotency-Key`. A same-key/same-payload retry returns the stored result without restarting synchronous effects; a different payload returns 409. A PostgreSQL unique constraint arbitrates concurrent first requests.
- Successful orders transition through `PENDING` → `INVENTORY_RESERVED` → `PAYMENT_AUTHORIZED` → `CONFIRMED`. Unknown SKU and insufficient stock persist as terminal `FAILED` orders (404 and 409). Invalid requests return 400 before insertion.
- Payment decline is stored by Payment Service. Order Service persists `COMPENSATION_REQUIRED`, then releases inventory. It reports terminal `FAILED`/`PAYMENT_DECLINED` only after Inventory confirms release; otherwise it remains visibly pending compensation and returns 503.
- A payment idempotency conflict remains `INVENTORY_RESERVED` with `MANUAL_REVIEW_REQUIRED`; the automated worker does not release inventory while a conflicting key could represent an authorization.
- Payment unavailability leaves `INVENTORY_RESERVED` for retry. An uncertain inventory timeout leaves `PENDING`; neither state claims a downstream effect that Order Service has not confirmed.
- Repeated inventory reserve/release and payment authorization use stable order IDs/keys. Conditional order updates prevent stale workers from overwriting terminal order states. This is at-least-once retry with idempotent effects, not exactly-once execution.
- Payment uses only synthetic amount units (quantity × 100) and a local provider simulator. No real payment details or external payment rail are supported.
- Failure header scenarios are validated and local-profile-only: inventory pre-mutation unavailable, inventory timeout after commit, payment decline, payment unavailable, payment timeout after commit, and decline plus failed compensation.
- `scripts/verify-saga-recovery.ps1` reproduces restart/recovery checks and is invoked by `scripts/test-backend.ps1`.

## Documentation and architecture

- README documents APIs, synthetic payment semantics, local failure controls, run/test commands, recovery, and consistency limits.
- `docs/architecture.md` documents state transitions, transaction boundaries, idempotency, retries, recovery, and missing production semantics.
- `docs/adr/0004-persisted-payment-saga.md` records the rationale and trade-offs.
- `docs/security.md` documents local-only controls, unauthenticated local APIs, and the no-sensitive-payment-data boundary.
- GitHub Actions now uses Compose plus the same pinned Maven Docker image for backend integration tests; it was not run on GitHub in this session.

## Remaining limitations / not verified

- The payment provider is only a deterministic simulator; there is no real charge, capture, void/refund workflow, or financial reconciliation.
- At the time of this payment-saga milestone, the application had no OpenTelemetry instrumentation, trace/correlation context propagation, Collector, metrics/traces/log backends, incident detection, FastAPI investigation API, or AI investigation. No telemetry or incidents were fabricated.
- At that time, the frontend was health-only and browser rendering against a running Vite server and Playwright workflows were not verified.
- GitHub Actions was updated but not executed remotely.
- These services share one PostgreSQL server, local credentials, and no authentication. The setup is for local development, not production deployment.
- Database outage recovery, multi-replica scheduling/claiming, provider authorization expiry, and automatic retry exhaustion/manual-operator procedures beyond the local endpoint need further testing/design.

## Phase 3 closeout update — 2026-10-10

- The local implementation and verification remain as recorded above: two serial backend runs passed 27 tests each, exported Tempo traces covered success and failure/recovery scenarios, Collector-outage behavior passed, frontend tests/build passed, and all eight Compose services were healthy during the recorded run.
- A manual Chrome spot-check showed the local Overview rendering, `GET /api/v1/health` returning HTTP 200, and the honest empty incident state. DevTools showed one cancelled health request and one successful request while the page remained functional. The cancellation was not diagnosed. The only console message in the supplied output was a `WindowMode` warning from an injected script; no TraceForge application error was identified. This was not exhaustive browser workflow testing.
- At the 2026-10-10 Phase 3 closeout, no Git remote was configured and remote CI was not run. An `origin` remote is configured in the current checkout, but no remote run is verified for the frontend dashboard.
- The legacy `SKU-TEST-ORDER` inconsistency documented above remains untouched.

## Current next milestone

The next closeout action is to review the current diff, then obtain explicit authorization to publish the reviewed branch changes so GitHub Actions can run. Hosted CI for this working tree remains unverified. Production authorization/database roles and mobile/exhaustive browser verification remain documented limitations; do not begin an unplanned phase.
