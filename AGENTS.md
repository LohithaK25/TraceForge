# TraceForge project instructions

## Project goals

- Build an evidence-first incident investigation platform. Deterministic collection and detection come before AI conclusions.
- Never fabricate incidents, traces, logs, metrics, evaluation results, or successful verification.
- Keep Java sample services, the Python investigation API, and the React dashboard independently understandable and runnable.

## Engineering rules

- Preserve existing user work; inspect files before changing or removing them.
- Prefer small vertical increments and explicit API contracts.
- Use strict TypeScript, typed Python request/response schemas, and Java tests for behavior that matters.
- Validate all input, bound network calls and payload sizes, and treat telemetry and model output as untrusted.
- Keep credentials in environment variables. Commit placeholders only.
- Run the relevant build and tests when toolchains are available; record exact commands and results in `TASKS.md`.
- Do not mark a feature complete based only on source code existing. State environmental blockers precisely.
- Update `TASKS.md` at the end of each implementation session.

## Repository map

- `services/`: Spring Boot sample services.
- `investigation/`: Python/FastAPI investigation backend (planned).
- `frontend/`: React, TypeScript, and Vite dashboard.
- `observability/`: version-controlled telemetry configuration (planned).
- `docs/`: architecture, roadmap, security, evaluation, and decisions.

## Local conventions

- Keep the local demo safe by default. Failure injection must be explicit and disabled outside local development.
- Do not expose management endpoints or unrestricted query/execution interfaces through user-facing APIs.
- Add a decision record for non-obvious architectural choices and update architecture docs when contracts change.
