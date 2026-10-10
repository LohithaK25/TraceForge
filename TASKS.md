# TraceForge task log

## Current verified state — 2026-10-10

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
- The application still has no OpenTelemetry instrumentation, trace/correlation context propagation, Collector, metrics/traces/log backends, incident detection, FastAPI investigation API, or AI investigation. No telemetry or incidents are fabricated.
- The frontend is still health-only. Browser rendering against a running Vite server and Playwright workflows were not verified.
- GitHub Actions was updated but not executed remotely.
- These services share one PostgreSQL server, local credentials, and no authentication. The setup is for local development, not production deployment.
- Database outage recovery, multi-replica scheduling/claiming, provider authorization expiry, and automatic retry exhaustion/manual-operator procedures beyond the local endpoint need further testing/design.

## Next milestone

Add OpenTelemetry server/client instrumentation and W3C trace-context propagation across Gateway, Order, Inventory, and Payment. Configure a minimal Collector and trace backend, then verify a confirmed order and each controlled failure produce queryable real traces and useful structured logs. Keep metrics/log stores and incident detection as a later incremental step.
