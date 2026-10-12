# Security notes

## Scope and assumptions

This is a local developer demo, not a production-secure multi-tenant service. The gateway exposes health, inventory-read, and order create/read/recovery routes without authentication. The manual recovery and failure-injection controls are accepted only when the Order, Inventory, and Payment services run with the explicit `local` profile. The trace query API and Grafana are also unauthenticated or use local placeholder credentials. Do not expose the demo stack to untrusted networks.

## Threats and controls

- **Secrets in source or logs:** use environment variables and `.env.example` placeholders; never log credentials, authorization headers, or payment secrets.
- **Failure controls abused remotely:** scenario headers are validated and rejected outside the `local` profile. Internal service ports are not published in Compose; only the gateway binds to loopback. Compose activates `local` for development and must not be used as a production profile.
- **Untrusted telemetry and prompt injection:** retrieved log content is data, never instructions. Bound and normalize evidence; validate all model citations against the retrieved set; do not execute generated recommendations.
- **Unbounded queries/network calls:** user-facing APIs must use fixed backend clients, allowlisted query parameters, timeouts, response-size limits, pagination, and safe error bodies. No arbitrary SQL, URL fetching, or shell endpoints.
- **Sensitive data exposure:** record only order identifiers, synthetic amount values, and authorization/decline metadata needed for the demo. Payment API accepts no PAN, bank credential, or other payment secret, and logs exclude payment details and idempotency headers.
- **Management surfaces:** keep Actuator and observability UIs on local-only ports; expose only required health/readiness endpoints.
- **Trace ingestion/query exposure:** only Grafana (`127.0.0.1:3000`) and Tempo's query API (`127.0.0.1:3200`) are published, bound to loopback. The Collector OTLP receiver and health endpoint, Tempo OTLP receiver, and all service-management ports stay inside the Compose network. This is a development boundary, not a replacement for authentication, TLS, or tenant isolation.
- **Observability runtime images:** the pinned upstream Tempo and Collector binaries are wrapped in Alpine only to provide `wget`-based Compose readiness probes. These wrappers do not publish additional ports or enable a management endpoint on the host.
- **Trace content and cardinality:** custom spans include order/reservation/authorization IDs and fixed outcome/error codes. IDs are trace attributes only, never metric labels. Custom spans omit SKU, payment amount/details, request bodies, authorization secrets, exception messages, and baggage. The agent's header/body capture settings remain off. Trace IDs are correlation identifiers, not credentials or authorization tokens; caller-supplied `traceparent` is accepted as correlation input and must not be trusted for identity or access control.
- **Trace retention and credentials:** Tempo uses a local Docker volume and a 24-hour completed-block retention. Grafana's example credentials are local placeholders; replace them in an ignored `.env` file for local use and never reuse them remotely. `docker compose down -v` deletes stored traces.
- **Telemetry outage behavior:** exporting runs asynchronously through the Java agent. A Collector/Tempo outage can lose or delay diagnostic spans, but must not convert a failed business call into a successful one. The local integration script checks this when the pipeline is available; telemetry loss during backend outages remains an operational limitation.
- **Investigation service boundary:** the Python service has no published host port. Its incident list/detail and detection-status APIs are internal and are exposed to local clients only through bounded, read-only gateway routes. Gateway parameters and upstream response size are capped; upstream calls have connect/read timeouts and return safe errors. The service's health and Order targets are fixed; Order pagination and terminal lookups are bounded. Evidence is structured and capped at 20 references per incident; raw response bodies and exception text are not persisted. The detector does not query Tempo. Its dedicated PostgreSQL schema is an ownership convention within the shared local database/user, not a database privilege boundary. The local gateway has no authentication or authorization; do not expose it or the Investigation Service beyond the local demo without an access-control and database-role design.
- **Dependency risk:** use supported versions and automated CI dependency/build checks; review updates rather than blindly auto-upgrading.

## Remaining limitations

- Local APIs have no authentication or authorization; recovery routes are for developer use only.
- Deterministic incident detection is scheduled and has bounded list/detail/status APIs through the gateway, but the frontend has no incident view yet. Local verification passed; remote CI remains unverified because no Git remote is configured. Browser rendering was only spot-checked during Phase 3 and was not rerun during the Phase 4 backend stage.
- `GET /internal/v1/orders/attention` returns active recovery cases. `GET /internal/v1/orders/recovery-observations` supplies explicit state for IDs attached to open recovery incidents. Missing IDs, unavailable sources, and stale observations do not resolve an incident.
- W3C trace state is propagated on synchronous HTTP edges; background recovery links preserve trace/span IDs but do not restore arbitrary caller `tracestate` or baggage.
- Compose port exposure and observability access controls require review before any non-local deployment. Tempo filesystem storage, single-instance retention, and local credentials are not production storage or access-control designs.
- Provider credentials, data retention, and model data handling require explicit review before enabling an external LLM.
- The project has not yet completed dependency vulnerability scanning or a deployment security review.

Do not describe this local demo as production-secure.
