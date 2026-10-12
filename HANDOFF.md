# TraceForge handoff

Updated 2026-10-12 after Phase 8 local closeout work. Read this with `CODEX_GUIDE.md`, then inspect live Git state before doing anything. The roadmap is authoritative. Locally achievable Phase 8 acceptance is complete, including an isolated nine-service cold start. Phase 8 remains open for hosted CI on the current uncommitted changes. Production authorization and separate PostgreSQL role enforcement remain unverified deployment limitations.

## Project and architecture

TraceForge is an evidence-first distributed incident investigation demo. The stack is a React 19 / TypeScript / Vite dashboard; four Java 21 / Spring Boot services; a Python 3.12 / FastAPI Investigation Service; PostgreSQL 16; and an OpenTelemetry Collector → Tempo → Grafana trace pipeline. Java builds/tests use the pinned Docker toolchain `maven:3.9.16-eclipse-temurin-21`; no host Maven install is needed.

| Component | Responsibility |
| --- | --- |
| API Gateway | Loopback-published browser/API entry point; proxies order, incident, detection-status, investigation, and sanitized trace routes. |
| Order Service | Owns durable orders and saga state; calls Inventory and Payment; retries/reconciles with scheduled recovery; serves private bounded recovery observations. |
| Inventory Service | Owns stock and idempotent reservation/release transactions. |
| Payment Service | Persists synthetic authorization/decline outcomes; it is not a real payment provider. |
| Investigation Service | Polls readiness and Order recovery state, applies deterministic rules, persists incidents/freshness, and generates a bounded evidence-backed report on request. It does not use Tempo for detection. |
| PostgreSQL | One local database with `order_service`, `inventory_service`, `payment_service`, and `incident_service` schemas. This is logical ownership, not separate DB-role security. |
| Collector / Tempo / Grafana | Collects and serves local traces; traces are optional supporting evidence. No metrics/logging backend is configured. |
| Frontend | Displays actual gateway health, incidents/history, source freshness, trace summaries, and saved/on-demand investigation results. |

Architecture and exact API contracts are in [`docs/architecture.md`](docs/architecture.md). Local startup and demo instructions are in [`docs/runbook.md`](docs/runbook.md).

## Git and preservation state

- Branch: `feature/phase4-incident-dashboard`.
- HEAD: `f006bde` (`docs: finalize Phase 6 verification and Phase 7 handoff`), tracking `origin/feature/phase4-incident-dashboard`.
- Phase 7 work and the Phase 8 documentation updates are uncommitted. At the Phase 8 inspection the staged diff was empty; nothing was staged, committed, or pushed. Always re-run `git status --short --untracked-files=all`, `git diff --stat`, and `git diff --cached --stat` before continuing; this handoff does not replace that live inventory.
- Preserve all tracked and untracked changes. Do not reset, revert, stash, discard, stage, commit, or push without explicit user authorization.

The original foundation commit is `e30a826`. The current branch history includes the Phase 4 dashboard checkpoint, Phase 5/6 documentation checkpoints, and the Phase 6 handoff at `f006bde`; the Phase 7 implementation and verification work is in the current uncommitted tree. See `git log --all --oneline` for exact history.

## Current milestones and verification

Phase 3 local distributed tracing and Phase 4–6 dashboard/detection/investigation work are documented in `docs/roadmap.md` and `TASKS.md`. Phase 7's local evaluation, controlled fault tests, and scoped live container-outage matrix were recorded as passing on 2026-10-12. The live matrix used disposable resources and left the default application volumes unchanged. It was not repeated during Phase 8.

Fresh Phase 8 checks on 2026-10-12:

- `.\scripts\test-investigation.ps1` with `DOCKER_CONTEXT=desktop-linux`: latest run **72 passed in 4.62s** on isolated tmpfs PostgreSQL. Evaluation: 10 scenarios; 10 successful POST runs; 9 latest snapshots; top-1/top-3 root-cause results 0/1 because the sole determinate case abstained; 47/47 citations valid; 0/26 unsupported factual claims under the fixture-backed oracle; latency p50 38.943 ms / p95 42.629 ms with in-process upstream fixtures; provider cost unavailable.
- `frontend`: `npm test` — **14 passed across 3 files**; `npm run build` — **passed**. Node 24.16.0 and npm 11.13.0 were used.
- `docker --context desktop-linux compose config -q` — **passed**. The default Compose project was already running and showed **9/9 healthy** services. The isolated test project had no remaining containers. `traceforge-postgres-data`, `traceforge-tempo-data`, and `traceforge-maven-cache` remained present.
- Read-only smoke checks: Gateway `GET /api/v1/health` **200**; `GET /api/v1/inventory/SKU-ALPHA` **200** with zero available units; `GET /api/v1/detection-status` **200 CURRENT** with five sources; open incident list **200**, empty.
- Isolated cold start: all nine disposable services reached healthy status. Gateway health, Inventory, Investigation readiness, and Grafana health returned 200. Detection status reached `CURRENT` with four monitored services `UP/CURRENT`; the open incident list was empty. The isolated project used a generated network, a unique PostgreSQL volume, tmpfs Tempo, unique build-image tags, and loopback-only test ports. Cleanup removed only this project's containers, network, images, and volume. Before/after snapshots showed the original nine services and three named volumes unchanged; the legacy SKU warning/data were untouched.
- The default stack was left running. Java unit suites, `scripts/test-backend.ps1`, live detection/trace verifiers, the Phase 7 outage matrix, and browser workflows were not rerun in this closeout. The cold-start check rebuilt and readiness-checked the Java images; previous test/live/browser results are historical evidence, not current-session reruns.
- `.github/workflows/ci.yml` was inspected. It runs frontend tests/build, the Investigation suite, four Java test suites, and Tempo trace verification on push/PR; it does not run the live Phase 7 outage matrix. `gh` is unavailable and the worktree changes are uncommitted, so hosted CI for the current changes is unverified. Running it requires an authorized commit/push or PR; none was performed.

Evaluation methodology and caveats are in [`docs/evaluation.md`](docs/evaluation.md) and [`docs/adr/0009-investigation-evaluation-and-resilience.md`](docs/adr/0009-investigation-evaluation-and-resilience.md). The root-cause scores are a limitation, not a pass threshold; the factual-oracle result is not an independent human review.

## Services and local endpoints

| Service | Host access |
| --- | --- |
| API Gateway | `http://localhost:8080` |
| Vite dashboard | `http://localhost:5173` after `npm run dev` |
| Tempo query API | `http://localhost:3200` |
| Grafana | `http://localhost:3000` |
| Order, Inventory, Payment, Investigation, PostgreSQL, Collector | Compose network only |

Gateway routes include `GET /api/v1/health`, `POST /api/v1/orders`, `GET /api/v1/incidents?status=OPEN|RESOLVED&limit=1..100`, `GET /api/v1/incidents/{id}`, `GET /api/v1/detection-status`, `GET /api/v1/traces/{traceId}`, `POST /api/v1/incidents/{id}/investigations`, and `GET /api/v1/incidents/{id}/investigations/latest`.

Detection freshness is separate from incident state: `NOT_RUN`, `CURRENT`, `PARTIAL`, `STALE`, or `UNAVAILABLE`. `SERVICE_NOT_READY` needs two consecutive qualifying failed probes to open and two UP probes to resolve. `ORDER_RECOVERY_STALLED` resolves only on explicit terminal Order state with required compensation complete. Stale/unavailable evidence never resolves an incident. Investigation reports distinguish facts, hypotheses, cited actions, source freshness, gaps, and uncertainty; `COMPLETE` means evidence completeness, not root-cause certainty.

## Safety and known data warning

This is an unauthenticated local demo, not production-secure. Do not expose it to untrusted networks. Do not delete named data volumes or reset the application database. Never alter or use the legacy `SKU-TEST-ORDER` fixture: it has 94 available units, 113 reservation rows, and 139 unreleased reserved units. The inconsistency is documented; it must remain untouched. `docker compose down -v` would delete persistent PostgreSQL and Tempo data.

Failure injection and manual recovery are enabled only in the local Spring profile. The report provider is deterministic; no external LLM or metered provider is configured. No root-cause ranking field, production authorization, separate database roles, remote CI result, or exhaustive/mobile browser verification is available.

## Next closeout action

Keep Phase 8 open until hosted CI runs for the reviewed changes. The single next action is to obtain explicit authorization to publish the current branch changes so the configured push/pull-request workflow can run. Do not begin another phase or claim production readiness.
