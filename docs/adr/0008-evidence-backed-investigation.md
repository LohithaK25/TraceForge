# ADR 0008: Evidence-backed investigation reports

- **Status:** Locally implemented, API/test verified, and selected-incident browser reviewed on 2026-10-12. Remote CI and production access controls are unverified.
- **Date:** 2026-10-12

## Context

Phase 4 supplies persisted deterministic incidents, service probe/freshness records, an Order-owned recovery observation API, and a Gateway API for bounded sanitized Tempo trace summaries. Operators need an evidence-backed report without allowing investigation to change incident lifecycle or turning missing telemetry into a healthy conclusion. The roadmap asks for normalized provenance, constrained output, citations, persistence, and explicit uncertainty. `.env.example` leaves `LLM_PROVIDER`, `LLM_API_KEY`, and `LLM_MODEL` blank; no tested external provider is selected.

## Decision

### Evidence boundary

The Investigation Service assembles evidence from the persisted incident/rule/evidence references, its own persisted detection health snapshot, a fixed Order Service recovery observation for recovery incidents, and optional trace summaries obtained through the Gateway's known trace-by-ID endpoint. It does not query Order, Inventory, or Payment tables. It never searches Tempo broadly. Trace summaries are already sanitized by the Gateway and validated again by the Investigation Service.

Evidence uses strict typed schemas and allowlisted fields, with source type/name/ID, observation time, freshness, fixed signal code, summary, and typed details. No request body/header, payment amount or credential, raw exception, arbitrary Tempo attribute, or response payload is persisted. Collection is bounded to 3 trace references, 20 spans per trace, a 1 MiB trace response, 100 evidence items, and 256 KiB persisted JSON. Existing client timeouts and a 10-second Gateway read timeout bound upstream work.

### Provider and output

`InvestigationProvider` returns a Pydantic-constrained `InvestigationContent`; `deterministic-v1` is the only configured adapter. It generates facts, qualified hypotheses, and suggested actions from the typed evidence set, not from free-form upstream text. The result contains `COMPLETE`, `PARTIAL`, or `INSUFFICIENT`, a human-readable uncertainty statement, evidence gaps, and per-run source freshness. Every claim has at least one citation, evidence identifiers must be unique, and the service rejects any citation that does not refer to evidence collected for that report.

`COMPLETE` means the required owning-service signal was current during collection; it does not establish causal root cause. `PARTIAL` marks stale, missing, contradictory, or unavailable relevant evidence. `INSUFFICIENT` means the required primary signal could not be confirmed. An absent optional trace reference is disclosed without being used as proof that a service is healthy. A referenced trace that cannot be queried makes the report partial. A terminal Order state that conflicts with an open recovery incident is surfaced as contradictory evidence; this report does not resolve the incident.

No external model call occurs. A future provider requires explicit credentials and a separately tested implementation that returns the same constrained schema and passes citation validation. Provider evaluation metrics and outage experiments belong to Phase 7, not this decision.

### API and persistence

- `POST /api/v1/incidents/{id}/investigations` collects and stores the latest report for an existing incident.
- `GET /api/v1/incidents/{id}/investigations/latest` returns the latest stored report.
- Both routes are proxied through fixed Gateway paths. A missing incident and an existing incident with no saved report use distinct 404 codes.
- Migration `0003_incident_investigations.sql` creates `incident_service.investigations`, with one JSONB snapshot per incident, an investigation UUID, generation time, and update time. A rerun replaces the latest snapshot rather than appending unbounded history.

The run endpoint changes only this Investigation-owned snapshot. It does not open/resolve incidents, update detector state, or modify business data. PostgreSQL schema ownership remains logical because the local services share credentials; production authorization and database role separation are not established here.

## Consequences

- Reports can be read after service restart and are traceable to exact collected evidence and source freshness.
- Deterministic incident detection remains the authority for opening/resolving episodes. Investigation findings and recommended actions are informational and never execute automatically.
- Partial source failures are explicit. The report cannot silently convert unavailable or stale evidence into a healthy result.
- Only the latest report per incident is retained. Historical investigation snapshots and model evaluation are intentionally deferred.
- The frontend supports saved-result, not-yet-run, running, error, and report states. Automated frontend tests/build passed. A real resolved incident's saved investigation panel was rendered, including citations, uncertainty, a trace gap, source freshness, and evidence; mobile layout and browser console/network logs were not inspected.
- The APIs remain unauthenticated local-demo endpoints. Do not expose them beyond loopback/local Compose without authorization, rate limiting, separate database roles, and a reviewed data-retention policy.

## Verification

On 2026-10-12, `scripts/test-investigation.ps1` passed 65 tests against isolated tmpfs PostgreSQL; the pinned Gateway suite passed 9 tests; frontend tests passed 14 tests and the production build passed. Compose configuration was valid and all 9 services were healthy before a targeted Investigation restart. A live investigation for an existing resolved service incident returned HTTP 200 with 8 evidence items and one optional gap, passed citation checks, and remained available with the same ID/generation time after restarting Investigation Service. The in-app browser rendered the Overview empty-open/freshness state and the saved investigation for a real resolved incident. A post-restart Compose health snapshot could not be obtained during closeout because Docker context/config and named-pipe access were denied. Remote CI, mobile rendering, browser console/network logs, production authorization, and database-role enforcement remain unverified. Exact command output and scope are recorded in [TASKS.md](../../TASKS.md).
