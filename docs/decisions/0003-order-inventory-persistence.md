# ADR 0003: Persist orders and inventory reservations in PostgreSQL

- **Status:** accepted
- **Date:** 2026-10-10

## Problem

The order-to-inventory slice needs durable order state and an inventory operation that really changes stock. Static fixtures or an in-memory order collection cannot support restart verification or honest reservation outcomes.

## Decision

Add one PostgreSQL service to local Compose with a named persistent volume. Order Service and Inventory Service own separate Flyway-managed schemas in the database. Order Service commits `PENDING_INVENTORY` before making the REST call. Inventory locks the SKU row and atomically decrements stock while recording an idempotent reservation keyed by order ID. Order Service reports `CONFIRMED` only after saving a matching reservation response.

On unknown SKU or insufficient stock, Inventory makes no stock change and Order Service persists a `REJECTED` outcome. For downstream errors, the order remains `PENDING_INVENTORY` without a reservation ID. A timeout may happen after the inventory transaction commits, so the actual remote outcome can be ambiguous; automatic reconciliation and compensation are not included in this increment.

The deterministic `inventory-unavailable` failure is enabled only under the explicit Spring `local` profile and fails before the inventory transaction. Both the order and inventory endpoints reject the failure header outside that profile.

## Alternatives and trade-offs

- An in-memory order list or inventory counter would lose state at restart and could not prove durable behavior.
- A database per service would strengthen isolation but adds another container and local operational overhead for this first order slice. Separate schemas preserve logical ownership on one local PostgreSQL server; credentials and server remain shared.
- A distributed transaction would be misleading across independent REST calls. Pending status makes uncertainty visible, but a timeout can leave stock reserved while the order remains pending until a future reconciliation path is implemented.

## Verification

The pinned Docker test suites exercise Flyway-backed persistence, stock updates, idempotent reservations, input and business rejections, and the controlled failure. Live Compose requests verified 201/404/409/400/503 behavior and stock deltas. A confirmed order remained readable after restarting Order Service while the PostgreSQL volume stayed mounted.
