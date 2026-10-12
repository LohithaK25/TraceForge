# Roadmap

## Phase 0 — inspect and plan

**Status: complete.** The repository, available toolchains, architecture, security assumptions, roadmap, and initial build/test-runtime decision are recorded.

## Phase 1 — runnable foundation

**Status: verified.** The actual gateway health route returned HTTP 200; the gateway JUnit test passed in the pinned Docker builder image; frontend unit tests and the production build passed; Compose configuration parsed and the gateway started healthy.

## Phase 2 — distributed sample application

**Status: verified.** The API gateway routes order create/read/recover calls. Order Service persists an idempotency key and saga state, reserves/releases inventory through Inventory Service, and authorizes through a separate Payment Service. All three services own Flyway-managed PostgreSQL schemas. Payment is a deterministic local simulator. The pinned Docker suites passed 25 tests, including real-network order integration, duplicate requests, declines, timeouts, and compensation. Live checks verified scheduled recovery and durable order, reservation, and authorization state across service restarts; exact commands/results are in `TASKS.md`.

## Phase 3 — distributed observability

**Status: locally implemented and verified (2026-10-10); remote CI remains unverified.** The gateway and three Java services use one pinned Java agent with custom order, inventory, payment, and linked recovery spans. The traces-only Collector → Tempo pipeline and provisioned Grafana Tempo data source ran in Compose. `scripts/test-backend.ps1` passed twice serially: the four Maven suites passed 27 tests on each run, saga restart/recovery assertions passed, and the acceptance script queried real Tempo traces for successful, rejected, declined/compensated, and outage/recovery flows. It verified the caller-supplied trace ID and parent span, expected service spans, and a distinct recovery trace linked to the source order span. The Collector outage check preserved the payment-decline and compensation business result. Frontend tests and production build passed, and all eight Compose services were healthy during recorded verification. A manual Chrome spot-check showed the Overview rendering, gateway health returning HTTP 200, and the honest empty incident state. DevTools showed one cancelled and one successful health request while the page remained functional; the cancellation was not diagnosed, and the supplied console output identified no TraceForge application error. This spot-check was not exhaustive browser workflow testing. No Git remote is configured, so no remote CI run is available. Loki and Prometheus remain out of scope; exact trace IDs and commands are in `TASKS.md`.

## Phase 4 — deterministic incident detection

**Status: backend implementation and local verification complete (2026-10-10); remote CI remains unverified.** The internal Investigation Service now runs scheduled bounded health and Order recovery collection, persists cycle/source freshness, applies the two deterministic rules, deduplicates incidents, and exposes bounded incident and detection-status reads through the gateway. Order provides explicit terminal observations for known open recovery incidents; missing Order records or unavailable/stale sources never resolve an incident. The isolated Investigation suite passed 53 tests. The pinned Java suites passed 37 tests, and live checks verified healthy/non-incident outcomes, incident opening/deduplication/resolution, source-failure behavior, service and Investigation restarts, and detection with the optional Collector stopped. Nine Compose services were healthy after verification. The dashboard still has no incident view. Browser workflow testing was not rerun in this backend stage, and no remote CI run is available because no Git remote is configured. See `TASKS.md`, the architecture section, and ADR 0006 for the exact evidence and remaining boundaries.

**Next:** Phase 5 adds a real incident list/detail and service/detection-freshness view to the dashboard, with explicit loading, empty, unavailable, and partial states. Keep browser workflow tests within that frontend milestone. Do not infer resolution from an empty attention page or missing telemetry.

## Phase 5 — dashboard

Add real incident list/detail, trace, and service-health views. Keep loading, empty, unavailable, and partial-data states explicit. Add browser workflow coverage after API contracts stabilize.

## Phase 6 — evidence-backed investigation

Extend the existing FastAPI service with evidence normalization, deterministic investigation, a schema-constrained provider adapter, citation validation, persistence, and explicit uncertainty. Use an LLM only when credentials and a tested provider are configured.

## Phase 7 — evaluation and resilience

Create fixed injected scenarios with known causes and ambiguous cases. Measure top-1 accuracy, top-3 recall, citation validity, unsupported-claim rate, latency, and cost when measurable. Run service, database, telemetry, and provider outage experiments.

## Phase 8 — portfolio release

Verify clean startup, complete runbooks, test/CI results, architecture diagram, reproducible evaluation, limitations, and a demo workflow.

## Acceptance discipline

Each phase is complete only after its behavior is exercised. A written plan or a configured service does not prove runtime integration. Never substitute fabricated telemetry or evaluation data for a missing dependency.
