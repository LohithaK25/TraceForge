# ADR 0005: Java-agent tracing with durable recovery links

- **Status:** Accepted for local development; local Phase 3 implementation and verification are complete; remote CI remains unverified
- **Date:** 2026-10-10

## Context

TraceForge uses four independent Spring Boot 4.1.1 applications compiled for Java 21. Their request edges are Spring MVC/Servlet server endpoints and Spring `RestClient` calls using `SimpleClientHttpRequestFactory`. The order recovery worker runs later than the original request, possibly after the originating HTTP span and process have ended. A local trace backend must be queryable so tests can prove propagation, not just Collector health.

## Decision

Attach the pinned OpenTelemetry Java agent `2.30.0` to each service's existing `eclipse-temurin:21-jre-alpine` image. Keep the existing `maven:3.9.16-eclipse-temurin-21` build path and fetch the agent artifact at image build. Add the aligned OpenTelemetry API `1.64.0` only where custom business spans are needed. Automatic instrumentation owns HTTP server/client spans and W3C Trace Context injection/extraction; application code must not add a second HTTP instrumentation layer.

Export OTLP/HTTP protobuf to the Compose-only Collector. The Collector forwards OTLP/gRPC to single-node Tempo `3.1.0`; Grafana `12.4.12` provisions Tempo for Explore. Tempo stores local trace blocks on a named volume. Only Grafana and Tempo's query API are published, both on loopback. Metrics and logs exporters are explicitly disabled in this phase.

Compose builds small Alpine wrappers around the pinned upstream Tempo and Collector binaries. The upstream runtime images are distroless/scratch, so they cannot execute shell-based HTTP health probes; the wrappers add `wget` for the actual readiness endpoints and retain non-root runtime users. The Collector health port remains private.

`order.create` persists the active trace/span IDs with the durable order row. Manual recovery remains in the incoming request trace and links to that origin. Scheduled recovery starts a new root trace and links its `order.recovery.worker` span to the origin. The origin IDs are internal database state and are not returned from order APIs. The worker does not restore `tracestate` or baggage; baggage is not configured.

## Alternatives considered

- **OpenTelemetry Spring Boot starter:** the official starter compatibility page documents Spring Boot 2.6+/3.1+, not Boot 4. A starter could require framework-specific compatibility fixes and library wiring for each app. The Java agent is the documented default with broader out-of-box instrumentation and avoids modifying Spring Boot's dependency graph.
- **Manual HTTP interceptors/filters everywhere:** these would duplicate edge instrumentation responsibility, risk inconsistent spans across four applications, and require extra code for each client/server path.
- **A trace-only deterministic in-memory exporter:** useful for unit tests but cannot prove production-style OTLP export, Collector forwarding, or Tempo queryability. It is used only for the focused recovery-link unit test; the local integration script queries Tempo directly.
- **Loki and Prometheus now:** the specification for this milestone asks for real distributed traces and explicitly defers extra logging/metrics infrastructure. Adding those backends would increase the local stack without improving this trace acceptance proof.

## Consequences and limits

- A pinned agent jar increases each service image size and startup work, but automatic instrumentation stays consistent and can be disabled with `TRACEFORGE_TRACING_ENABLED=false` without modifying business code.
- Trace export is asynchronous and best effort. A Collector/Tempo outage may make evidence unavailable but must not rewrite the HTTP or saga outcome.
- `parentbased_always_on` makes local validation deterministic. It is not an appropriate default sampling policy for a high-volume production deployment.
- Order and operation IDs are high-cardinality span attributes, not metric labels. No request body, SKU, payment amount/details, authorization secret, or custom exception message is added.
- Recovery links are durable across service restarts. Link records retain trace/span IDs, but not arbitrary W3C `tracestate`; baggage is disabled.
- Tempo local storage and 24-hour block retention are for development, not a backup or production retention policy.

## Verification

`OrderTracingTest` uses an in-memory exporter to check root/parent behavior and origin links. `scripts/verify-traces.ps1` sends known W3C `traceparent` values and polls Tempo's documented `GET /api/v2/traces/{traceID}` endpoint for the expected service spans, exported payment span status, and recovery links. It also stops the local Collector for one deterministic payment-decline request and asserts that the failed payment and successful compensation remain visible as the business result, then restores the Collector from a `finally` block even if the stop command partially fails. On 2026-10-10, two serial runs of `scripts/test-backend.ps1` passed the 27 backend tests, saga restart checks, and Tempo-exported trace checks; the latest trace IDs and exact results are in `TASKS.md`. A manual Chrome spot-check showed the local Overview rendering, HTTP 200 from the gateway health endpoint, and the honest empty incident state. One cancelled and one successful health request appeared in DevTools while the page remained functional; the cancellation was not diagnosed, and the supplied console output identified no TraceForge application error. This was not exhaustive browser workflow testing. Remote CI remains unverified because no Git remote is configured and no remote run is available.

## References

- [OpenTelemetry Java agent for Spring Boot](https://opentelemetry.io/docs/zero-code/java/spring-boot-starter/)
- [OpenTelemetry Java agent supported libraries](https://opentelemetry.io/docs/zero-code/java/agent/supported-libraries/)
- [Grafana Tempo HTTP API](https://grafana.com/docs/tempo/latest/api_docs/)
- [Grafana Tempo local filesystem deployment](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/deploy/locally/linux/)
