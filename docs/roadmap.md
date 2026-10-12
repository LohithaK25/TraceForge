# Roadmap

## Phase 0 — inspect and plan

**Status: complete.** The repository, available toolchains, architecture, security assumptions, roadmap, and initial build/test-runtime decision are recorded.

## Phase 1 — runnable foundation

**Status: verified.** The actual gateway health route returned HTTP 200; the gateway JUnit test passed in the pinned Docker builder image; frontend unit tests and the production build passed; Compose configuration parsed and the gateway started healthy.

## Phase 2 — distributed sample application

**Status: verified.** The API gateway routes order create/read/recover calls. Order Service persists an idempotency key and saga state, reserves/releases inventory through Inventory Service, and authorizes through a separate Payment Service. All three services own Flyway-managed PostgreSQL schemas. Payment is a deterministic local simulator. The pinned Docker suites passed 25 tests, including real-network order integration, duplicate requests, declines, timeouts, and compensation. Live checks verified scheduled recovery and durable order, reservation, and authorization state across service restarts; exact commands/results are in `TASKS.md`.

## Phase 3 — distributed observability

**Status: locally implemented and verified (2026-10-10); remote CI remains unverified.** The gateway and three Java services use one pinned Java agent with custom order, inventory, payment, and linked recovery spans. The traces-only Collector → Tempo pipeline and provisioned Grafana Tempo data source ran in Compose. `scripts/test-backend.ps1` passed twice serially: the four Maven suites passed 27 tests on each run, saga restart/recovery assertions passed, and the acceptance script queried real Tempo traces for successful, rejected, declined/compensated, and outage/recovery flows. It verified the caller-supplied trace ID and parent span, expected service spans, and a distinct recovery trace linked to the source order span. The Collector outage check preserved the payment-decline and compensation business result. Frontend tests and production build passed, and all eight Compose services were healthy during recorded verification. A manual Chrome spot-check showed the Overview rendering, gateway health returning HTTP 200, and the honest empty incident state. DevTools showed one cancelled and one successful health request while the page remained functional; the cancellation was not diagnosed, and the supplied console output identified no TraceForge application error. This spot-check was not exhaustive browser workflow testing. No remote was configured at that verification time, so remote CI was not run. An `origin` remote is configured now, but no remote CI result is verified. Loki and Prometheus remain out of scope; exact trace IDs and commands are in `TASKS.md`.

## Phase 4 — deterministic incident detection

**Status: backend verified (2026-10-10); frontend incident dashboard and desktop browser check verified locally (2026-10-12).** The internal Investigation Service runs scheduled bounded health and Order recovery collection, persists cycle/source freshness, applies the two deterministic rules, deduplicates incidents, and exposes bounded incident and detection-status reads through the gateway. Order provides explicit terminal observations for known open recovery incidents; missing Order records or unavailable/stale sources never resolve an incident. The previously reported isolated Investigation suite passed 53 tests, the pinned Java suites passed 37 tests, and live checks verified healthy/non-incident outcomes, incident opening/deduplication/resolution, source-failure behavior, service and Investigation restarts, and detection with the optional Collector stopped. The dashboard now reads open incidents, resolved history, incident details, and detection-source freshness through the gateway. On 2026-10-12, its 9 frontend tests and production build passed, and read-only requests through the Vite proxy returned HTTP 200 for health, incident list, and detection-status endpoints. The desktop browser showed the honest empty-open state, current freshness for five sources, resolved history, and a real incident detail; no console errors/warnings or horizontal overflow were observed at 1280×720. Mobile/exhaustive browser coverage and remote CI remain unverified. Backend suites and Compose health were not rerun in the frontend session. See `TASKS.md`, the architecture section, and ADR 0006 for evidence and remaining boundaries.

The dashboard's incident-list/detail and detection-freshness slice is implemented and desktop browser-verified. Empty incidents do not imply health; stale or unavailable sources remain separately visible. Mobile/exhaustive browser coverage and remote CI remain outstanding. Do not infer resolution from an empty attention page or missing telemetry.

## Phase 5 — dashboard

**Status: implemented and locally verified for the documented scope.** The `detection-status` response reports the last persisted probe result and freshness independently for each of the four monitored services. The Gateway provides a fixed, validated, size/time-bounded Tempo trace-by-ID read which exposes a sanitized span summary. The dashboard distinguishes service status from observation freshness and lazily loads trace evidence only when requested. On 2026-10-12, the isolated Investigation suite passed 54 tests and the pinned Gateway suite passed 8 tests. The rebuilt services returned four service snapshots and a real caller-correlated four-span Gateway/Inventory trace; malformed/missing IDs returned 400/404, Tempo unavailability returned 503, and Tempo was restored healthy. The live deterministic verifier passed incident, recovery, restart/freshness, and Collector-independence checks. Frontend tests (11) and production build passed in the recorded Phase 5 run; they were not rerun during the later backend verification. Four supplied desktop screenshots manually document per-service probe health/freshness, separate detection-source freshness, the honest empty-open state, real resolved history and incident evidence, and trace evidence when no trace reference is present. This verifies only the visible desktop workflows in those screenshots, not every interaction, network request, mobile layout, or exhaustive browser workflow. Browser automation had previously blocked direct navigation to the local URL. Remote CI, production authorization, and separate database-role enforcement remain outstanding; see `TASKS.md` for the recorded evidence and limitations.

## Phase 6 — evidence-backed investigation

Extend the existing FastAPI service with evidence normalization, deterministic investigation, a schema-constrained provider adapter, citation validation, persistence, and explicit uncertainty. Use an LLM only when credentials and a tested provider are configured.

## Phase 7 — evaluation and resilience

Create fixed injected scenarios with known causes and ambiguous cases. Measure top-1 accuracy, top-3 recall, citation validity, unsupported-claim rate, latency, and cost when measurable. Run service, database, telemetry, and provider outage experiments.

## Phase 8 — portfolio release

Verify clean startup, complete runbooks, test/CI results, architecture diagram, reproducible evaluation, limitations, and a demo workflow.

## Acceptance discipline

Each phase is complete only after its behavior is exercised. A written plan or a configured service does not prove runtime integration. Never substitute fabricated telemetry or evaluation data for a missing dependency.
