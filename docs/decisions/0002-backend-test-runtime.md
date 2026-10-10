# ADR 0002: Run backend tests in the pinned Docker builder image

- **Status:** accepted
- **Date:** 2026-10-10

## Problem

The repository needs a repeatable way to run Java tests without requiring developers to install Maven system-wide or match a specific host JDK.

## Decision

Use the same `maven:3.9.16-eclipse-temurin-21` image declared by the service Dockerfiles. The repository script `scripts/test-backend.ps1` starts the Compose PostgreSQL service, mounts each service source tree into a one-shot builder container on the Compose network, and uses a Docker named volume for Maven's dependency cache.

## Alternatives and trade-offs

- A local JDK 21 + Maven 3.9+ gives the fastest IDE/debug loop but requires manual machine setup.
- A Maven Wrapper is safe to commit and avoids a system-wide Maven install, but bootstraps a Maven distribution into the user's cache and runs on the host JDK. This project already requires Docker and pins its production builder/runtime to Java 21, so a container reduces toolchain drift.
- The dedicated container needs Docker Desktop and an initial Maven Central download. The named cache volume speeds later runs; it is independent of repository files and can be removed if the developer intentionally clears Docker caches.

## Verification

Run `./scripts/test-backend.ps1` from the repository root. It runs the gateway, inventory, and order suites, stops on the first service test failure, and returns Maven's exit code. PostgreSQL remains running and existing database contents are preserved.
