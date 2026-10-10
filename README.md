# TraceForge

TraceForge is an evidence-first distributed incident investigation project. Its runnable sample application now demonstrates a durable order → inventory reservation → payment authorization saga. The dashboard still shows only live gateway health; it does not invent orders, payments, incidents, traces, metrics, or investigation results.

## Current implementation

- API Gateway, Order Service, Inventory Service, Payment Service, and PostgreSQL run in Docker Compose.
- Orders, reservations, and payment attempts use separate PostgreSQL schemas and Flyway migrations on the persistent `traceforge-postgres-data` volume.
- Order creation uses a required client idempotency key. Inventory reservation, inventory release, and payment authorization are each idempotent at their service boundary.
- A persisted recovery worker resumes uncertain operations and compensation. See [docs/architecture.md](docs/architecture.md) for the state machine and consistency limits.
- The payment provider is a deterministic local simulator. No real payment rail, card number, or other payment credential is accepted or processed.

## Prerequisites

- Docker Desktop with Linux containers enabled.
- Node.js 22.12 or later and npm to run the dashboard.
- A local Java 21 JDK and Maven are optional. Backend builds and tests use the pinned `maven:3.9.16-eclipse-temurin-21` image; service images run on `eclipse-temurin:21-jre-alpine`.

PostgreSQL credentials in `.env.example` are local-development placeholders. Do not reuse them outside the local demo.

## Run locally

From the repository root:

```powershell
docker compose up --build -d --wait
```

Only the gateway is published, on `127.0.0.1:8080`. Order, Inventory, Payment, and PostgreSQL have no host-published ports. Compose enables the `local` Spring profile for this demo, which gates the deterministic failure controls and manual recovery endpoint.

To run the dashboard in another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open the Vite URL printed by the command. The dashboard checks `GET /api/v1/health` through the Vite proxy and remains health-only.

## Order API

Create an order through the gateway. `Idempotency-Key` is required and must be reused for an exact retry of the same payload.

```http
POST http://localhost:8080/api/v1/orders
Content-Type: application/json
Idempotency-Key: demo-order-001

{"sku":"SKU-ALPHA","quantity":2}
```

An initial success returns HTTP 201 with `status: "CONFIRMED"`, an inventory reservation ID, and a payment authorization ID. Each demo unit is assigned 100 synthetic minor units for the simulator; this value is not a product price or a real charge. Read the stored result with `GET /api/v1/orders/{id}`.

Repeating the same key and payload returns the original order without starting new side effects. Reusing its key with a different SKU or quantity returns HTTP 409. Input validation requires SKU syntax `[A-Z0-9][A-Z0-9-]{0,31}` and quantity 1–1000; invalid requests return HTTP 400 before insertion.

| Outcome | Order state | HTTP result |
| --- | --- | --- |
| Inventory reserved and payment authorized | `CONFIRMED` | 201 |
| Unknown SKU | `FAILED` / `UNKNOWN_SKU` | 404 |
| Insufficient stock | `FAILED` / `INSUFFICIENT_STOCK` | 409 |
| Payment declined and inventory release completed | `FAILED` / `PAYMENT_DECLINED`, `inventoryReleased: true` | 402 |
| Inventory/payment outcome uncertain or dependency unavailable | `PENDING` or `INVENTORY_RESERVED` | 503 |
| Payment decline awaiting inventory release | `COMPENSATION_REQUIRED` | 503 |

## Internal service APIs

Payment Service accepts `POST /internal/v1/payments/authorizations` with `Idempotency-Key` and a validated `{ "orderId": "…", "amountMinor": 200 }` body. It returns a persisted `AUTHORIZED` or `DECLINED` result. Repeating the key and same details returns that row; a changed order or amount returns 409. Inventory Service releases a hold through `POST /internal/v1/inventory/reservations/{orderId}/release`. Both internal services are reachable only on the Compose network.

## Local recovery and controlled failures

`POST /api/v1/orders/{id}/recover` asks Order Service to make one idempotent recovery attempt. It is enabled only in the `local` profile. A scheduled worker also scans persisted recoverable orders every five seconds; each retry is delayed at least 15 seconds and automatic retries stop after ten failed attempts. An exhausted order remains visible with `recoveryError: "AUTOMATIC_RETRIES_EXHAUSTED"` and can be manually retried in the local profile.

Use the optional `X-TraceForge-Failure` header on a create request to reproduce a controlled path:

| Header value | Expected persisted behavior |
| --- | --- |
| `inventory-unavailable` | Inventory fails before mutation; order stays `PENDING`. |
| `inventory-timeout-after-commit` | Reservation commits, response is delayed past the Order Service timeout; recovery finds the same reservation and does not decrement twice. |
| `payment-decline` | Declined payment is persisted; Inventory releases the reservation; order becomes `FAILED`. |
| `payment-unavailable` | No payment attempt is persisted; order stays `INVENTORY_RESERVED` and can be retried. |
| `payment-timeout-after-commit` | Authorization persists before the response timeout; retry returns the same authorization. |
| `payment-decline-compensation-unavailable` | Decline persists, release fails before mutation, order remains `COMPENSATION_REQUIRED`; recovery later releases stock. |

All injected scenarios are rejected outside the explicit `local` profile. They do not accept or log sensitive payment data. The local profile is for development only.

## Consistency guarantees and limits

Each service commits only to its own schema; there is no distributed transaction. The order row is durable before downstream calls. Inventory commits a stock decrement and reservation together; release restores that quantity and records `released_at` in one transaction and is idempotent by order ID. Payment commits an authorization/decline keyed by the order UUID. The saga uses persisted state transitions and compare-and-set updates, idempotency keys, bounded retries, and compensation.

This does not provide exactly-once execution. A timeout can hide a successful reservation or authorization commit, so the order records an unknown outcome and retries the same idempotency key. The order reports a reservation ID only after Inventory confirms it. A payment decline is not terminal until inventory release succeeds. If the process or database is unavailable during compensation, `COMPENSATION_REQUIRED` remains persisted for later recovery. The three schemas share one PostgreSQL server and local credentials; this is a development sample, not a production security/availability design.

A payment idempotency-key conflict is held at `INVENTORY_RESERVED` for manual review; the system does not release stock while the conflicting key could refer to an existing authorization.

## Verify

```powershell
.\scripts\test-backend.ps1
cd frontend
npm test
npm run build
cd ..
docker compose config -q
```

The backend script builds/starts the Compose stack, then runs Gateway, Inventory, Payment, and real-network Order integration suites in one-shot `maven:3.9.16-eclipse-temurin-21` containers. The Maven cache is stored in the `traceforge-maven-cache` Docker volume. Exact verified test counts and live checks are recorded in [TASKS.md](TASKS.md).

## Stop and reset

- Stop the dashboard with `Ctrl+C`.
- Stop Compose with `docker compose down`; the database volume remains.
- To intentionally erase stored orders, reservations, and payment attempts, use `docker compose down -v`.

## Roadmap and references

See [docs/roadmap.md](docs/roadmap.md), [docs/architecture.md](docs/architecture.md), [docs/security.md](docs/security.md), and [docs/adr/0004-persisted-payment-saga.md](docs/adr/0004-persisted-payment-saga.md).
