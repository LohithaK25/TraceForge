$ErrorActionPreference = 'Stop'

$baseUrl = 'http://localhost:8080'

function Invoke-TraceForgeRequest {
    param(
        [Parameter(Mandatory)] [string] $Method,
        [Parameter(Mandatory)] [string] $Path,
        [hashtable] $Headers = @{},
        [string] $Body
    )

    $arguments = @{
        Uri = "$baseUrl$Path"
        Method = $Method
        Headers = $Headers
        SkipHttpErrorCheck = $true
        TimeoutSec = 15
    }
    if ($null -ne $Body) {
        $arguments.ContentType = 'application/json'
        $arguments.Body = $Body
    }
    $response = Invoke-WebRequest @arguments
    $json = $null
    if ($response.Content) {
        $json = $response.Content | ConvertFrom-Json
    }
    return [pscustomobject]@{ Status = [int] $response.StatusCode; Body = $json }
}

function Get-TestStock {
    $response = Invoke-TraceForgeRequest -Method Get -Path '/api/v1/inventory/SKU-TEST-ORDER'
    if ($response.Status -ne 200) { throw "Inventory read failed with HTTP $($response.Status)" }
    return [int] $response.Body.availableQuantity
}

function Restart-OrderWithDependencies {
    & docker compose stop order-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop order-service' }
    & docker compose restart inventory-service payment-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart inventory/payment services' }
    & docker compose start order-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not start order-service' }
    & docker compose up -d --wait order-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'order-service did not become healthy' }
}

function Restart-OrderAndInventory {
    & docker compose stop order-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop order-service' }
    & docker compose restart inventory-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart inventory-service' }
    & docker compose start order-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not start order-service' }
    & docker compose up -d --wait order-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'order-service did not become healthy' }
}

function Assert-Status {
    param($Response, [int] $Expected, [string] $Scenario)
    if ($Response.Status -ne $Expected) {
        throw "$Scenario expected HTTP $Expected, got $($Response.Status): $($Response.Body | ConvertTo-Json -Compress)"
    }
}

$stockBefore = Get-TestStock
$key = "restart-recovery-$([guid]::NewGuid())"
$created = Invoke-TraceForgeRequest -Method Post -Path '/api/v1/orders' `
    -Headers @{ 'Idempotency-Key' = $key; 'X-TraceForge-Failure' = 'payment-unavailable' } `
    -Body '{"sku":"SKU-TEST-ORDER","quantity":1}'
Assert-Status $created 503 'payment-unavailable order'
if ($created.Body.status -ne 'INVENTORY_RESERVED' -or -not $created.Body.inventoryReservationId) {
    throw 'Expected a persisted reservation and recoverable payment state before restarting services'
}
if ((Get-TestStock) -ne ($stockBefore - 1)) { throw 'Expected exactly one committed reservation before restart' }

Restart-OrderWithDependencies
$recovered = $null
$recoveryDeadline = (Get-Date).AddSeconds(45)
do {
    $probe = Invoke-TraceForgeRequest -Method Get -Path "/api/v1/orders/$($created.Body.id)"
    if ($probe.Status -eq 200 -and $probe.Body.status -eq 'CONFIRMED') {
        $recovered = $probe
        break
    }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $recoveryDeadline)
if ($null -eq $recovered -or -not $recovered.Body.paymentAuthorizationId) {
    throw 'The scheduled worker did not recover the persisted order after the services restarted'
}
Write-Host 'PASS: scheduled recovery resumed an order after Order, Inventory, and Payment service restarts'
$repeated = Invoke-TraceForgeRequest -Method Post -Path "/api/v1/orders/$($created.Body.id)/recover"
if ($repeated.Body.paymentAuthorizationId -ne $recovered.Body.paymentAuthorizationId) {
    throw 'Repeated recovery changed the payment authorization'
}
if ((Get-TestStock) -ne ($stockBefore - 1)) { throw 'Recovery duplicated or released the inventory reservation' }
Write-Host 'PASS: reserved order and stock persisted across restarts; repeated recovery was idempotent'

$stockBeforePaymentTimeout = Get-TestStock
$timeoutKey = "payment-timeout-restart-$([guid]::NewGuid())"
$paymentTimeout = Invoke-TraceForgeRequest -Method Post -Path '/api/v1/orders' `
    -Headers @{ 'Idempotency-Key' = $timeoutKey; 'X-TraceForge-Failure' = 'payment-timeout-after-commit' } `
    -Body '{"sku":"SKU-TEST-ORDER","quantity":1}'
Assert-Status $paymentTimeout 503 'payment timeout after commit'
if ($paymentTimeout.Body.status -ne 'INVENTORY_RESERVED') { throw 'Expected authorization outcome to remain recoverable after timeout' }
$orderId = [string] $paymentTimeout.Body.id
$persistedAuthorization = (& docker compose exec -T postgres psql -U traceforge -d traceforge -Atc `
    "SELECT authorization_id FROM payment_service.payment_attempts WHERE order_id = '$orderId'").Trim()
if ($LASTEXITCODE -ne 0 -or -not $persistedAuthorization) { throw 'Payment authorization was not persisted before the induced timeout' }

& docker compose stop order-service | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not stop order-service before payment restart' }
& docker compose restart payment-service | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not restart payment-service' }
& docker compose start order-service | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not start order-service after payment restart' }
& docker compose up -d --wait order-service | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'order-service did not become healthy after payment restart' }
$paymentRecovered = Invoke-TraceForgeRequest -Method Post -Path "/api/v1/orders/$orderId/recover"
Assert-Status $paymentRecovered 200 'payment recovery after service restart'
if ($paymentRecovered.Body.status -ne 'CONFIRMED' -or $paymentRecovered.Body.paymentAuthorizationId -ne $persistedAuthorization) {
    throw 'Recovery did not return the payment authorization persisted before restart'
}
if ((Get-TestStock) -ne ($stockBeforePaymentTimeout - 1)) { throw 'Payment recovery changed inventory more than once' }
Write-Host 'PASS: payment authorization persisted across Payment Service restart and timeout recovery'

$stockBeforeCompensation = Get-TestStock
$compensationKey = "compensation-restart-$([guid]::NewGuid())"
$compensation = Invoke-TraceForgeRequest -Method Post -Path '/api/v1/orders' `
    -Headers @{ 'Idempotency-Key' = $compensationKey; 'X-TraceForge-Failure' = 'payment-decline-compensation-unavailable' } `
    -Body '{"sku":"SKU-TEST-ORDER","quantity":1}'
Assert-Status $compensation 503 'failed compensation'
if ($compensation.Body.status -ne 'COMPENSATION_REQUIRED') { throw 'Expected compensation to remain visibly pending' }
if ((Get-TestStock) -ne ($stockBeforeCompensation - 1)) { throw 'Expected the reservation to remain held while compensation was pending' }

Restart-OrderAndInventory
$compensated = Invoke-TraceForgeRequest -Method Post -Path "/api/v1/orders/$($compensation.Body.id)/recover"
Assert-Status $compensated 200 'compensation recovery after service restart'
if ($compensated.Body.status -ne 'FAILED' -or -not $compensated.Body.inventoryReleased) {
    throw 'Expected confirmed compensation to produce a failed, released order'
}
$compensatedAgain = Invoke-TraceForgeRequest -Method Post -Path "/api/v1/orders/$($compensation.Body.id)/recover"
if ($compensatedAgain.Body.status -ne 'FAILED' -or (Get-TestStock) -ne $stockBeforeCompensation) {
    throw 'Repeated recovery changed the compensated order or stock quantity'
}
Write-Host 'PASS: compensation intent survived restart, released inventory once, and remained terminal'
