# Roadmap

## Phase 0 — inspect and plan

**Status: complete.** The repository, available toolchains, architecture, security assumptions, roadmap, and initial build/test-runtime decision are recorded.

## Phase 1 — runnable foundation

**Status: verified.** The actual gateway health route returned HTTP 200; the gateway JUnit test passed in the pinned Docker builder image; frontend unit tests and the production build passed; Compose configuration parsed and the gateway started healthy.

## Phase 2 — distributed sample application

**Status: verified.** The API gateway routes order create/read/recover calls. Order Service persists an idempotency key and saga state, reserves/releases inventory through Inventory Service, and authorizes through a separate Payment Service. All three services own Flyway-managed PostgreSQL schemas. Payment is a deterministic local simulator. The pinned Docker suites passed 25 tests, including real-network order integration, duplicate requests, declines, timeouts, and compensation. Live checks verified scheduled recovery and durable order, reservation, and authorization state across service restarts; exact commands/results are in `TASKS.md`.

## Phase 3 — observability (next)

Instrument HTTP server/client spans and W3C context propagation after the payment path exists. Add version-controlled Collector, Tempo, Loki, Prometheus, and Grafana configuration. Exercise one successful and one failing order, then verify trace, metrics, and logs in their backends.

## Phase 4 — deterministic detection

Add PostgreSQL and migrations, bounded telemetry queries, configurable threshold rules, incident grouping/deduplication, recovery, and evidence references. Test thresholds, traffic minimums, and repeat detections.

## Phase 5 — dashboard

Add real incident list/detail, trace, and service-health views. Keep loading, empty, unavailable, and partial-data states explicit. Add browser workflow coverage after API contracts stabilize.

## Phase 6 — investigation

Add FastAPI contracts, evidence normalization, deterministic investigator, schema-constrained provider adapter, citation validation, persistence, and explicit uncertainty. Use an LLM only when credentials and a tested provider are configured.

## Phase 7 — evaluation and resilience

Create fixed injected scenarios with known causes and ambiguous cases. Measure top-1 accuracy, top-3 recall, citation validity, unsupported-claim rate, latency, and cost when measurable. Run service, database, telemetry, and provider outage experiments.

## Phase 8 — portfolio release

Verify clean startup, complete runbooks, test/CI results, architecture diagram, reproducible evaluation, limitations, and a demo workflow.

## Acceptance discipline

Each phase is complete only after its behavior is exercised. A written plan or a configured service does not prove runtime integration. Never substitute fabricated telemetry or evaluation data for a missing dependency.
