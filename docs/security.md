# Security notes

## Scope and assumptions

This is a local developer demo, not a production-secure multi-tenant service. The gateway exposes health, inventory-read, and order create/read/recovery routes without authentication. The manual recovery and failure-injection controls are accepted only when the Order, Inventory, and Payment services run with the explicit `local` profile. Do not expose the demo stack to untrusted networks.

## Threats and controls

- **Secrets in source or logs:** use environment variables and `.env.example` placeholders; never log credentials, authorization headers, or payment secrets.
- **Failure controls abused remotely:** scenario headers are validated and rejected outside the `local` profile. Internal service ports are not published in Compose; only the gateway binds to loopback. Compose activates `local` for development and must not be used as a production profile.
- **Untrusted telemetry and prompt injection:** retrieved log content is data, never instructions. Bound and normalize evidence; validate all model citations against the retrieved set; do not execute generated recommendations.
- **Unbounded queries/network calls:** user-facing APIs must use fixed backend clients, allowlisted query parameters, timeouts, response-size limits, pagination, and safe error bodies. No arbitrary SQL, URL fetching, or shell endpoints.
- **Sensitive data exposure:** record only order identifiers, synthetic amount values, and authorization/decline metadata needed for the demo. Payment API accepts no PAN, bank credential, or other payment secret, and logs exclude payment details and idempotency headers.
- **Management surfaces:** keep Actuator and observability UIs on local-only ports; expose only required health/readiness endpoints.
- **Dependency risk:** use supported versions and automated CI dependency/build checks; review updates rather than blindly auto-upgrading.

## Remaining limitations

- Local APIs have no authentication or authorization; recovery routes are for developer use only.
- Compose port exposure and observability access controls require review before any non-local deployment.
- Provider credentials, data retention, and model data handling require explicit review before enabling an external LLM.
- The project has not yet completed dependency vulnerability scanning or a deployment security review.

Do not describe this local demo as production-secure.
