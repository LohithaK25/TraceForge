# Prompt for the next Codex session

Continue TraceForge Phase 4 by implementing the frontend incident dashboard in the existing repository at `E:\Projects`.

First read `CODEX_GUIDE.md`, `HANDOFF.md`, the repository's current instructions, and refresh `git status --short --untracked-files=all`. Preserve every existing tracked and untracked change. Do not stage, commit, push, reset, stash, revert, discard, or overwrite existing work. Do not reset the database, alter legacy records, or delete named Docker volumes. Do not rewrite the backend, invent endpoints, weaken tests, or start unrelated features.

Before coding, inspect the actual React/TypeScript/Vite conventions, components, styles, tests, current gateway health client, and the current Investigation/Gateway response models and routes. The existing frontend currently fetches only `GET /api/v1/health`; its incident panel is a placeholder even though backend APIs now exist. Vite proxies `/api` to `http://localhost:8080`.

Use the existing read-only contracts:

- `GET /api/v1/incidents?status=OPEN|RESOLVED&limit=1..100&cursor=<opaque>` (default OPEN/50) returns `{ items, limit, nextCursor, detectionStatus }`.
- `GET /api/v1/incidents/{uuid}` returns an incident detail.
- `GET /api/v1/detection-status` returns `status` (`NOT_RUN`, `CURRENT`, `PARTIAL`, `STALE`, `UNAVAILABLE`), optional `latestCycle`, and per-source freshness (`CURRENT`, `PARTIAL`, `STALE`, `UNAVAILABLE`, with `attemptedAt`, nullable `lastSuccessAt`, `itemCount`, and nullable `errorCode`).
- Incident records have `id`, `ruleKey`, `severity`, `status` (`OPEN`/`RESOLVED`), `scopeType`, `sourceReference`, timestamps, `occurrenceCount`, `summary`, bounded `evidence`, and nullable trace IDs among other fields. Re-read the real model before deciding what to show.

Build a minimal, useful dashboard using real API responses only. Make loading, successful empty results, open incidents, resolved history, stale/partial/unavailable detection sources, and request/API errors visibly distinct. Do not interpret an empty list or missing telemetry as healthy; show source freshness separately from incident state. Use the existing opaque cursor only as an opaque value. Do not render fabricated examples or claim a trace exists unless its actual ID is present. Keep sensitive/high-cardinality identifiers out of broad summary surfaces unless needed for a selected incident.

Add focused frontend tests for the actual response shapes and key states, including empty/open/resolved data and stale/unavailable/error handling. Run `npm test` and `npm run build` from `frontend`. If browser automation is available, start or reuse the local stack safely, open the Vite app, and verify the overview, incident list/detail, loading/empty/failure states, network requests, console, and obvious layout issues. Do not claim browser verification if it was not performed. The prior Chrome check was only a Phase 3 Overview spot-check; it did not cover incidents. Remote CI has not run and is reported unavailable because no Git remote is configured.

Use the backend baseline recorded in `TASKS.md` and `HANDOFF.md`: Phase 4 reported 53 isolated Investigation tests and 37 Java tests passing, actual Tempo traces queried, detection open/deduplicate/resolve/freshness/restart checks passing, and nine Compose services healthy. These are prior results, not tests to claim as newly run. Do not rerun the full backend suite unless a concrete frontend integration issue requires it.

After implementation, update `TASKS.md` and relevant frontend-facing documentation with only the checks actually run, inspect the final diff, and report changed files, exact test/build/browser results, limitations, and next work. Stop at the frontend dashboard milestone; do not commit.
