# Prompt for the next Codex session: Phase 6

> Archived historical prompt. The roadmap has since advanced through Phase 7 and is in Phase 8; do not use the Phase 6 instructions below as the current project task. Read `HANDOFF.md`, `TASKS.md`, and `docs/roadmap.md` for the current state.

Continue TraceForge Phase 6, Evidence-Backed Investigation, in E:/Projects. Implement the roadmap milestone after first inspecting the current repository. Do not start Phase 7 or Phase 8.

## Refresh and preserve the repository state

The last recorded checkpoint is branch feature/phase4-incident-dashboard at commit 8209ac1 (feat: complete Phase 4 incident dashboard). Phase 5 backend, frontend, and documentation changes are uncommitted. At the end of the 2026-10-12 handoff closeout, Git showed 19 modified tracked files and 9 untracked files, with no staged changes. Refresh git status, staged and unstaged diffs, branch, and HEAD before editing because this inventory may have changed. Preserve all tracked and untracked work. Do not reset, revert, stash, discard, stage, commit, or push anything without explicit user authorization.

## Read the project contract first

Read AGENTS.md, CODEX_GUIDE.md, HANDOFF.md, TASKS.md, README.md, docs/roadmap.md, docs/architecture.md, docs/security.md, and all relevant ADRs, especially ADRs 0004 through 0007. Inspect the actual Phase 6 acceptance criteria in the roadmap and architecture, the current Investigation Service models/routes/repository/migrations/tests, the incident and evidence APIs, trace summary contract, and the frontend integration points before proposing or changing implementation. Treat repository code and current docs as the source of truth; do not invent endpoints, response fields, provider behavior, or requirements.

## Current implementation and recorded baseline

TraceForge is an evidence-first local demo: React/TypeScript/Vite dashboard; Java 21/Spring Boot Gateway, Order, Inventory, and Payment services; Python 3.12/FastAPI Investigation Service; PostgreSQL; OpenTelemetry Collector, Tempo, and Grafana. The Investigation Service owns scheduled deterministic incident detection, freshness, incident persistence, and read APIs. It uses health and explicit Order recovery observations; Tempo is optional supporting evidence and is not a detection input. The dashboard reads real Gateway APIs and does not fabricate incidents or telemetry.

Phase 5 records locally verified backend/runtime behavior: the Investigation suite passed 54 tests in its isolated tmpfs PostgreSQL setup; the pinned Docker JDK 21/Maven Gateway suite passed 8 tests; Compose validation passed; the rebuilt Gateway and Investigation image IDs matched their new tags; all nine Compose services were healthy at the final recorded check; and scripts/verify-detection.ps1 passed opening, deduplication, resolution, freshness persistence, restart, and Collector-outage independence checks. A real trace read returned four sanitized Gateway/Inventory spans; malformed, absent, and Tempo-unavailable reads returned 400, 404, and 503, and Tempo was restored. The frontend test suite passed 11 tests and the production build passed in the recorded run; they were not rerun during the later backend verification. The full scripts/test-backend.ps1 was not run during that Phase 5 verification.

Four supplied desktop screenshots manually document the Phase 5 per-service health/probe freshness, separate detection-source freshness, honest empty-open-incidents message, real resolved SERVICE_NOT_READY history, a detail with HEALTH_PROBE / CONNECT_FAILED evidence, and a trace-evidence section when no trace references are returned. This is limited visual evidence for the visible desktop states. It does not establish every interaction, network request, mobile layout, or exhaustive browser behavior. An earlier automation attempt was blocked from navigating to the local URL. Remote CI is unverified. Production authorization and separate database-role enforcement are unverified. Do not present these recorded results as tests rerun in your session.

The legacy SKU-TEST-ORDER data warning remains: 94 available units versus 113 reservation rows representing 139 unreleased units. Do not inspect-and-reconcile, alter, or reuse these records. Do not reset application data or delete named Docker volumes.

## Phase 6 objective and boundaries

The roadmap defines Phase 6 as extending the existing FastAPI Investigation Service with evidence normalization, deterministic investigation, a schema-constrained provider adapter, citation validation, persistence, and explicit uncertainty. An LLM is used only when credentials and a tested provider are configured. The architecture also calls for activation, incident reads, normalized evidence, constrained provider adapters, and validated citations; keep evaluation and resilience experiments within Phase 7 unless the existing roadmap explicitly requires a small dependency.

Implement the complete Phase 6 acceptance scope found in the repository, not a guessed substitute. Reuse the current incident, Order/recovery, health, and trace evidence APIs and preserve their trust boundaries. Do not fabricate incidents, evidence, traces, telemetry, citations, or investigation results. Clearly distinguish observed facts from hypotheses, attach provenance to evidence and claims, and represent missing, stale, unavailable, or contradictory evidence as uncertainty. Bound inputs, network timeouts, payload sizes, provider output, and error handling as required by the established architecture.

Keep deterministic incident detection independent of investigation or AI code. Follow existing provider/model configuration and security guidance. Do not introduce an external provider, API-key dependency, paid service, or new infrastructure unless the roadmap and architecture explicitly support it. If no tested provider is configured, the application must not imply an LLM investigation occurred. Integrate the results with existing APIs and dashboard only where the roadmap requires it; use real responses and existing UI conventions.

## Verification and documentation

Add meaningful unit, integration, persistence, citation/provenance, uncertainty, and failure-path tests that match the actual Phase 6 design. Verify behavior with healthy, missing, stale, unavailable, and contradictory evidence as appropriate. Inspect any stateful verifier's cleanup logic before running it. Run focused tests first, then relevant backend/frontend tests and builds, safe integration checks, and git diff --check. Use the pinned Docker JDK 21/Maven backend workflow where applicable. Report exact commands and results, distinguishing checks actually run from the baseline above; identify blocked or unrun checks without implying they passed. Update TASKS.md, README.md, architecture/security documentation, ADRs when a new non-obvious decision is required, and HANDOFF.md to match actual implementation and verification.

## Safety constraints

- Never reset, revert, stash, or discard existing work.
- Never stage, commit, or push without explicit user authorization.
- Never delete named Docker volumes or reset application data.
- Never alter or reuse the documented legacy SKU-TEST-ORDER records.
- Inspect cleanup logic before stateful verification; do not clean records outside the verifier's unique fixtures.
- Do not weaken tests or claim unexecuted tests, browser checks, remote CI, or runtime checks passed.
- Do not implement Phase 7 or Phase 8 as part of Phase 6 unless the original roadmap explicitly makes a small dependency necessary; do not skip those phases' planned functionality.
- Preserve the remote-CI, production-authorization, and separate database-role-enforcement caveats until verified.
- Keep changes incremental and within the Phase 6 scope. Do not add Kafka, Kubernetes, a new workflow engine, unrelated features, or an unapproved external provider.

After Phase 6 is implemented and verified, report the next milestone as Phase 7, Evaluation and Resilience. Do not begin it in this task.
