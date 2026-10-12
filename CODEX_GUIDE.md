# Codex guide for TraceForge

- Read `HANDOFF.md`, applicable `AGENTS.md` instructions, and the current Git status before editing. Treat the handoff's Git inventory as a snapshot and inspect the live tree.
- Preserve all tracked and untracked work. Never reset, revert, stash, discard, or overwrite user changes.
- Never reset/delete named database volumes or alter the documented legacy `SKU-TEST-ORDER` records. Do not use that fixture in tests.
- Do not stage, commit, or push unless the user explicitly authorizes it.
- Work incrementally. Avoid rebuilding completed milestones; use existing APIs, schemas, styles, and test conventions. Run focused tests first, then the relevant broader checks.
- Never claim a test, build, browser check, live integration check, or CI run passed unless it was actually executed and its result inspected. Separate prior reported results from checks run in the current session.
- Update documentation only to describe real implementation changes and checks actually run. Do not edit docs merely to make a milestone appear complete.
- Keep scope bounded to the user's request. Ask before expanding into unrelated features, backend/API changes, infrastructure, or destructive runtime/database actions.
- Keep the local demo evidence-first: do not fabricate incidents, traces, metrics, or success states. Treat missing/stale source data as unknown, not healthy.
- Before stateful verification, inspect the verifier's cleanup logic and identify exactly which records or services it may change.
- Never delete named Docker volumes or reset application data. Preserve the documented legacy SKU-TEST-ORDER records and warning.
- Do not implement Phase 7 or Phase 8 as part of Phase 6 unless the original roadmap explicitly requires a small dependency; do not skip their planned functionality.
- Preserve the remote-CI, production-authorization, and separate database-role-enforcement caveats until those checks are actually verified.
