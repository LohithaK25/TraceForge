# ADR 0004: Persisted payment and compensation saga

- **Status:** Accepted
- **Date:** 2026-10-10

## Context

Orders, inventory reservations, and payment attempts are owned by independent services. Their writes share a local PostgreSQL server but use separate schemas and local transactions. A network timeout can occur after a downstream commit, so a synchronous call chain alone cannot tell whether an operation happened. Repeating a non-idempotent operation with a new identity could duplicate a reservation or authorization.

## Decision

Persist the order's idempotency key, request payload, saga state, downstream identifiers, retry metadata, and compensation outcome in the Order Service schema. Use the order UUID as the stable inventory reservation/release key and payment authorization key. Payment Service stores one immutable simulator outcome per key. Inventory stores a durable reservation and `released_at` marker; reservation and release are transactional and idempotent.

Order transitions are compare-and-set updates. A local scheduled scanner retries due nonterminal work with a 15-second per-order delay and a ten-failure automatic retry limit. Payment decline moves to `COMPENSATION_REQUIRED` before Inventory is asked to release. The order reaches `FAILED` only after the release is confirmed. Manual recovery is local-profile-only.

## Consequences

- A retry can safely repeat a request whose result was hidden by a timeout, without asserting exactly-once network delivery.
- Order state remains observable when a dependency is down, and compensation can resume after a process restart.
- Compensation can be pending indefinitely if Inventory remains unavailable. Manual intervention is needed after automatic retries are exhausted.
- There is no atomic transaction spanning schemas/services, no outbox, real payment provider, authorization void/refund, or broker. This simulator's `DECLINED` result is definitive and has no external monetary effect.
- All schemas share a local PostgreSQL server and demo credentials; this ADR does not define production security or availability.

## Alternatives not selected

- A cross-service distributed transaction would add coupling and availability demands without a concrete need in this sample.
- Kafka or a workflow engine would add infrastructure for one order flow; persisted state and idempotent REST operations are sufficient at this scale.
- An in-memory retry queue would lose recovery intent on restart and is therefore not acceptable.
