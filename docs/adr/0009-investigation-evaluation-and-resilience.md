# ADR 0009: Investigation evaluation and resilience boundaries

- **Status:** Accepted; local evaluation, controlled fault tests, and the scoped live container-outage matrix are verified. Remote CI and production access controls remain unverified.
- **Date:** 2026-10-12

## Context

Phase 7 requires repeatable investigation scenarios, quality metrics, and failure experiments without allowing investigation to mutate deterministic incident lifecycle or business state. The configured `deterministic-v1` provider returns facts, qualified hypotheses, and actions. It does not expose a ranked root-cause candidate field, and it makes no metered external provider call.

## Decision

- Keep a fixed `traceforge-investigation-phase7-v1` scenario suite in `investigation/tests/test_phase7_evaluation.py`. It calls the real Investigation API and persists results only in the isolated, tmpfs-backed test PostgreSQL schema. Fixed in-process upstream clients inject health, Order, and trace observations/failures. No application database or business-service table is used.
- Compute top-1 accuracy and top-3 recall only from an explicit ranked-cause contract. The current API has none, so unranked hypotheses and factual failure codes are not promoted to predictions. A determinate known-cause case with no candidate is recorded as an abstention and scores as a miss; ambiguous cases are excluded from those denominators.
- Validate citation IDs mechanically and review factual claims against scenario-specific typed evidence and exact deterministic wording. Assert each scenario's source freshness and status-specific uncertainty, along with the expected evidence gaps and report completeness. Report the fixture-backed review method and sample size; it is not an independent blind human review.
- Measure latency around successful API POSTs through PostgreSQL persistence with fixed in-process upstream fixtures. Treat the result as a local test measurement, not a production SLO. Report cost as unavailable when no metered provider is configured.
- Inject provider unavailability through `InvestigationProviderUnavailable`; expose only HTTP 503 `INVESTIGATION_PROVIDER_UNAVAILABLE`. Database persistence errors remain HTTP 503 `DETECTION_STORE_UNAVAILABLE`. Neither path saves a report or changes incident lifecycle.
- Exercise bounded client timeouts, failed/malformed/oversized responses, trace unavailability, stale/partial/contradictory evidence, repeated requests, and concurrent latest-snapshot writes. These tests do not stop live Compose application services or the persistent database.

## Consequences

The evaluation is reproducible and safe to rerun. The latest 2026-10-12 Phase 8 rerun passed the full Investigation suite (72 tests in 4.62s). It measured top-1 0/1 and top-3 0/1 because the one determinate cause was not ranked; citation validity was 47/47; the fixture oracle found 0 unsupported factual claims among 26 reviewed; and local persisted API latency was p50 38.943 ms / p95 42.629 ms across 10 successful POST runs. The tests assert that the terminal confirmed-order decision is `RESOLVE` and creates no record without an open episode. Freshness/uncertainty assertions exposed and verified a fix for stale health evidence being described as current. Cost was unavailable. These are measurements and limitations, not acceptance thresholds.

No new provider, retry policy, queue, cache, circuit breaker, infrastructure, or incident lifecycle behavior is introduced. Controlled fault tests are distinct from the live container matrix, which was separately verified with a disposable Compose project and exact project-scoped cleanup; see [the evaluation record](../evaluation.md). Remote CI, production authorization, and separate database-role enforcement remain outstanding, so local Phase 7 acceptance is recorded separately from broader production/release sign-off. See [TASKS.md](../../TASKS.md).
