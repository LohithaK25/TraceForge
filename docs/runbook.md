# TraceForge local runbook

This is a local developer/demo stack, not a production deployment. Use PowerShell from the repository root. The default Compose project has nine services: `api-gateway`, `order-service`, `inventory-service`, `payment-service`, `investigation-service`, `postgres`, `otel-collector`, `tempo`, and `grafana`.

## Start and smoke-check the stack

Prerequisites are Docker Desktop in Linux-container mode plus Node.js 22.12 or later and npm for the frontend. Java and Maven are not required on the host; Java tests use the pinned Docker builder image. If the default Docker context is inaccessible on this Windows host, select the working Docker Desktop context for this PowerShell process only:

```powershell
$env:DOCKER_CONTEXT = 'desktop-linux'
docker compose config -q
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration is invalid' }
docker compose up --build -d --wait
if ($LASTEXITCODE -ne 0) { throw 'Compose startup did not complete successfully' }
docker compose ps --all
```

The gateway publishes `http://127.0.0.1:8080`, Tempo's query API publishes `http://127.0.0.1:3200`, and Grafana publishes `http://127.0.0.1:3000`. Application services, PostgreSQL, the Collector receivers, and the Investigation Service are private to the Compose network. Grafana's local default credentials are documented in `.env.example`; change them in an ignored `.env` before any use beyond a trusted local machine.

Use the versioned product health contract and inspect detection freshness separately from findings:

```powershell
$base = 'http://127.0.0.1:8080'
Invoke-RestMethod "$base/api/v1/health"
$detection = Invoke-RestMethod "$base/api/v1/detection-status"
$detection | Select-Object status, latestCycle, sources
$open = Invoke-RestMethod "$base/api/v1/incidents?status=OPEN&limit=25"
$open.items | Select-Object id, ruleKey, severity, sourceReference, summary
```

An empty incident list is not proof of health. Read `detection-status` and the per-source freshness values (`CURRENT`, `PARTIAL`, `STALE`, or `UNAVAILABLE`) independently. A stale or failed source does not resolve an incident.

## Run the dashboard

In another PowerShell terminal:

```powershell
Set-Location frontend
npm ci
npm test
npm run build
npm run dev
```

Open the Vite URL printed by `npm run dev` (the configured default is `http://localhost:5173`). Vite proxies `/api` requests to the Gateway on port 8080. The dashboard reads real health, incident, detection-status, trace, and investigation responses. It does not seed or invent incidents.

## Reproduce a normal order safely

First check the available quantity rather than assuming the persistent demo SKU has stock:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/inventory/SKU-ALPHA'
```

For a repeatable success even when `SKU-ALPHA` has been consumed, create a unique test SKU with the repository's scoped helper. This writes one synthetic SKU and order to the persistent local database; the `finally` block removes only that generated SKU and the order, reservation, and payment rows addressed by the unique key.

```powershell
. .\scripts\TraceForgeTestData.ps1
$demoSku = New-TraceForgeTestSku -Prefix 'DEMO' -Quantity 4
$demoKey = "tf-demo-$([guid]::NewGuid().ToString('N'))"
try {
    $order = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/v1/orders' -Method Post `
        -Headers @{ 'Idempotency-Key' = $demoKey } `
        -ContentType 'application/json' `
        -Body (@{ sku = $demoSku; quantity = 1 } | ConvertTo-Json -Compress)
    $order | Select-Object id, status, failureReason, inventoryReleased
} finally {
    Remove-TraceForgeTestData -IdempotencyKeys @($demoKey) -Skus @($demoSku)
}
```

On success, the API returns HTTP 201 and a durable `CONFIRMED` order. For an exact idempotent retry, reuse the same key and same body. A changed body with that key returns HTTP 409. The payment service is a local simulator; order amounts are synthetic and are not charges.

## Demonstrate detection and investigation

The supported live demonstration is `scripts/verify-detection.ps1`. It creates unique synthetic test data and exercises healthy/compensated outcomes, incomplete compensation, incident deduplication and resolution, recovery-source failure, and service readiness. It restores services in `finally` and cleans the exact generated business rows and order incidents. It temporarily stops/restarts Order, Inventory, the Collector, and Investigation; run it only against the local demo stack when that interruption is acceptable. Resolved service-health incidents remain in history, and trace data may remain in Tempo. Do not use or clean up the legacy `SKU-TEST-ORDER` fixture.

```powershell
$env:DOCKER_CONTEXT = 'desktop-linux'
.\scripts\verify-detection.ps1
```

The script reports real IDs and state returned by the APIs. After it finishes, inspect findings and freshness through the dashboard or these read-only APIs:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/incidents?status=OPEN&limit=50'
Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/incidents?status=RESOLVED&limit=50'
Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/detection-status'
```

For an existing incident, the dashboard's **Run investigation** action calls `POST /api/v1/incidents/{id}/investigations`; it persists only the latest report snapshot in `incident_service`. `GET /api/v1/incidents/{id}/investigations/latest` reads that snapshot. The report is deterministic, cites only collected evidence, labels source gaps and freshness, and does not change the incident or business workflow. If no incident exists, do not invent one; use the controlled local verifier when its effects are acceptable.

## Inspect actual traces

Run the trace acceptance script when you want to prove export and cross-service propagation rather than just see a healthy Collector:

```powershell
$env:DOCKER_CONTEXT = 'desktop-linux'
.\scripts\verify-traces.ps1
```

It sends real orders with known W3C context, polls Tempo for exported spans, and prints trace IDs. The script temporarily stops and restores the local Collector, creates business records, and can consume inventory for successful/outage-recovered orders. Query an emitted trace with `GET http://localhost:3200/api/v2/traces/{traceId}` or open Grafana Explore at `http://localhost:3000` and query by trace ID. Tempo stores local traces on `traceforge-tempo-data` with bounded retention; trace evidence is optional for detection.

## Tests and what they exercise

| Check | Command | Scope and side effects |
| --- | --- | --- |
| Compose syntax | `docker compose config -q` | Resolves configuration; does not start services. |
| Investigation and evaluation | `$env:DOCKER_CONTEXT='desktop-linux'; .\scripts\test-investigation.ps1` | Builds the pinned Python image and uses its isolated test project and tmpfs PostgreSQL data; application schemas and named data volumes are not used. The script removes its test database container. |
| Frontend tests/build | `Set-Location frontend; npm test; npm run build` | Vitest plus TypeScript and Vite production build. |
| Full backend/live checks | `.\scripts\test-backend.ps1` | Uses the running application database and Compose stack, runs Java suites plus saga/detection/trace verifiers, and temporarily interrupts selected local services. Inspect its cleanup effects before use. |
| Live incident verifier | `.\scripts\verify-detection.ps1` | See the demo section; generated order data is scoped/cleaned, service-health history and traces may remain. |
| Tempo trace verifier | `.\scripts\verify-traces.ps1` | See trace section; actual exported spans are queried, and its local failure scenario temporarily stops the Collector. |
| Isolated outage matrix | `.\scripts\verify-phase7-outages.ps1 -RunOutages` | Uses an isolated Compose project and generated PostgreSQL volume, stops only that disposable project's services, then performs label-checked project-scoped cleanup. Do not substitute broad Docker cleanup. |

The GitHub Actions workflow at `.github/workflows/ci.yml` runs the frontend tests/build, isolated Investigation suite, Java service suites in the pinned Maven/JDK 21 image, and Tempo trace verifier on pushes and pull requests. It does not run the Phase 7 live container-outage matrix. A local pass does not prove hosted CI passed; check the run for the exact commit being reviewed.

## Preserve data

The default application database and Tempo blocks live on named volumes. Do not use `docker compose down -v` as routine cleanup: it deletes the named PostgreSQL and Tempo volumes. Never remove volumes to repair a test. Stopping the default Compose project interrupts every service and is outside the verification performed here; only stop it when that impact is intended and the project identity is confirmed. The known `SKU-TEST-ORDER` state is inconsistent (94 available units versus 113 reservation rows totaling 139 unreleased units); preserve it and do not use it in demos or tests.

## Verified limitations

- This is an unauthenticated local demo, not production-secure. Production authorization and separate PostgreSQL database-role enforcement remain unverified.
- Remote CI is not verified for the current uncommitted working tree. Do not push without authorization.
- The latest evaluation has no ranked-cause output: top-1 and top-3 are each 0/1 because its one determinate scenario abstains. Citation and factual-oracle results apply only to the fixed fixture dataset (latest: 47/47 citations and 0/26 unsupported claims); persisted API latency was p50 38.943 ms / p95 42.629 ms with in-process upstream fixtures.
- No provider cost is available; the configured investigation provider makes no metered external call.
- Earlier browser checks cover selected desktop views; mobile/exhaustive browser workflows and remote CI remain unverified.
- The existing default Compose project was left running. A separate, disposable nine-service cold-start project reached 9/9 healthy and passed read-only checks for Gateway health, Inventory, Investigation readiness, Grafana health, current detector freshness, and the empty open-incident list. Its unique network, PostgreSQL volume, images, and containers were cleaned; the default project and its named volumes matched before/after snapshots. This does not mean the existing default project was stopped or restarted.
