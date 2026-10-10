# ADR 0001: Initial stack and service boundaries

- **Status:** accepted for the first increment
- **Date:** 2026-10-10

## Problem

Establish a small, runnable foundation that fits the requested portfolio stack while keeping incident evidence grounded in real systems.

## Decision

Use Spring Boot 4.1.1 and Java 21 for business services, React 19.3 + strict TypeScript + Vite 8 for the dashboard, and FastAPI for the separate investigation API. The initial increment started with an API gateway health contract and a dashboard that displays its actual response. Use Maven for Java and REST for the first service boundaries. PostgreSQL was deferred until an order/inventory workflow needed durable state; ADR 0003 records that persistence decision.

## Alternatives and trade-offs

- A single framework for all services would simplify local startup but would not demonstrate the requested Java business services and Python investigation boundary.
- Spring Cloud Gateway could provide richer routing but adds complexity before there is a route graph to manage.
- A fabricated dashboard dataset would make the screen look populated while weakening evidence integrity; the initial UI instead reports real health and honest unavailable states.
- Boot 4.1.1 uses newer Spring modules. The pinned Docker builder supplies and verifies JDK 21 and Maven, so a matching host installation is unnecessary for the repository test path.

## Failure modes and tests

The API may be unreachable or return an invalid response; the frontend displays an error and does not present guessed status. The gateway contract is covered by a MockMvc integration test, and the dashboard health rendering is covered by Vitest/Testing Library tests. Both suites have been run successfully; current results are recorded in `TASKS.md`.
