# Prompt for the next Codex session

The existing TraceForge Phase 4 incident-dashboard milestone is implemented and its desktop browser closeout is verified. Do not restart implementation or begin another phase without an explicit user request.

First read `CODEX_GUIDE.md`, `HANDOFF.md`, `TASKS.md`, and current repository instructions. Inspect `git status --short --untracked-files=all` and the current diff. Preserve every existing tracked and untracked change. Do not stage, commit, push, reset, stash, revert, discard, or overwrite work. Do not modify or delete database records or named Docker volumes. Never touch the documented inconsistent `SKU-TEST-ORDER` data.

The dashboard implementation already exists in `frontend/src/api/incidents.ts` and `frontend/src/components/IncidentDashboard.tsx`; `App.tsx` integrates it into Overview. It uses the existing gateway routes only:

- `GET /api/v1/health`
- `GET /api/v1/incidents?status=OPEN|RESOLVED&limit=1..100&cursor=<opaque>`
- `GET /api/v1/incidents/{uuid}`
- `GET /api/v1/detection-status`

It shows open incidents, resolved history, selected incident evidence, and detection-source freshness separately. Empty results, loading, request/API errors, stale/partial/unavailable sources, and not-run data have distinct states. Do not add sample incidents, fabricate success, or treat stale/missing sources as healthy.

Frontend checks recorded in `TASKS.md`: `npm test` passed 2 files / 9 tests and `npm run build` passed. Vite-proxy calls returned HTTP 200 for gateway health, the empty open-incident list (`CURRENT`), and detection status (`CURRENT`, five sources). The desktop browser check displayed the empty open state and freshness panel, resolved history, and a real resolved incident detail; it found no console errors/warnings or horizontal overflow at 1280×720. Mobile/exhaustive browser coverage remains unverified. `docker compose ps` was blocked by Docker named-pipe permissions, so Compose health was not freshly verified. The previously reported 53 Investigation tests, 37 Java tests, traces, and detection/restart checks were not rerun during the frontend work.

No additional Phase 4 dashboard work is pending from this verification. If a later user request asks for changes, first inspect the actual repository and preserve the current worktree; do not infer or invent the next feature. Do not use persistent data to manufacture a browser demonstration.

Remote CI has not been verified; do not push or trigger a run. Production authentication/authorization and separate PostgreSQL-role verification remain outstanding. Do not implement trace UI, AI investigation, or another phase without the user's next scoped request.
