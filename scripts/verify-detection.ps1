$ErrorActionPreference = 'Stop'

$baseUrl = 'http://localhost:8080'
. (Join-Path $PSScriptRoot 'TraceForgeTestData.ps1')
$testSku = New-TraceForgeTestSku -Prefix 'DETECT' -Quantity 40
$testKeys = [System.Collections.Generic.List[string]]::new()
$inventoryStopped = $false
$orderStopped = $false
$collectorStopped = $false
$investigationRestartRequired = $false

function Invoke-DetectionRequest {
    param([Parameter(Mandatory)] [string] $Method, [Parameter(Mandatory)] [string] $Path,
          [hashtable] $Headers = @{}, [string] $Body)
    $args = @{ Uri = "$baseUrl$Path"; Method = $Method; Headers = $Headers; SkipHttpErrorCheck = $true; TimeoutSec = 10 }
    if ($null -ne $Body) { $args.ContentType = 'application/json'; $args.Body = $Body }
    $response = Invoke-WebRequest @args
    $json = if ($response.Content) { $response.Content | ConvertFrom-Json } else { $null }
    return [pscustomobject]@{ Status = [int]$response.StatusCode; Body = $json }
}

function Get-OrderIncident {
    param([Parameter(Mandatory)] [string] $OrderId, [Parameter(Mandatory)] [string] $Status)
    $page = Invoke-DetectionRequest -Method Get -Path "/api/v1/incidents?status=$Status&limit=100"
    if ($page.Status -ne 200) { throw "Incident list returned HTTP $($page.Status)" }
    return @($page.Body.items | Where-Object { $_.ruleKey -eq 'ORDER_RECOVERY_STALLED' -and $_.sourceReference -eq $OrderId } | Select-Object -First 1)
}

function Wait-OrderIncident {
    param([string] $OrderId, [string] $Status, [int] $TimeoutSeconds = 30)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $items = Get-OrderIncident -OrderId $OrderId -Status $Status
        if ($items.Count -gt 0) { return $items[0] }
        Start-Sleep -Seconds 1
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "Timed out waiting for order incident status $Status"
}

function Wait-DetectionCycles {
    param([DateTimeOffset] $After, [int] $Count = 2, [int] $TimeoutSeconds = 25)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    $seen = [System.Collections.Generic.HashSet[string]]::new()
    do {
        $result = Invoke-DetectionRequest -Method Get -Path '/api/v1/detection-status'
        if ($result.Status -ne 200) { throw "Detection status returned HTTP $($result.Status)" }
        $cycle = $result.Body.latestCycle
        if ($null -ne $cycle -and $cycle.status -ne 'RUNNING' -and ([DateTimeOffset]$cycle.startedAt) -gt $After) {
            [void]$seen.Add([string]$cycle.cycleId)
        }
        if ($seen.Count -ge $Count) { return }
        Start-Sleep -Seconds 1
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Count completed detection cycles"
}

function Remove-DetectionTestIncidents {
    param([string[]] $IdempotencyKeys)

    $keys = @($IdempotencyKeys | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    if ($keys.Count -eq 0) { return }
    foreach ($key in $keys) {
        if ($key -notmatch '^tf-det-[a-f0-9]{32}$') { throw 'Refusing to clean incidents for an unrecognized detection test key' }
    }
    $keyList = ($keys | ForEach-Object { "'$_'" }) -join ', '
    $rawIds = Invoke-TraceForgePostgresSql -Sql "SELECT id::text FROM order_service.orders WHERE idempotency_key IN ($keyList)"
    $orderIds = @($rawIds -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^[0-9a-fA-F-]{36}$' } | Select-Object -Unique)
    if ($orderIds.Count -eq 0) { return }
    $idList = ($orderIds | ForEach-Object { "'$_'" }) -join ', '
    [void](Invoke-TraceForgePostgresSql -Sql "DELETE FROM incident_service.incidents WHERE rule_key = 'ORDER_RECOVERY_STALLED' AND scope_type = 'ORDER' AND source_reference IN ($idList)")
    $remaining = [int](Invoke-TraceForgePostgresSql -Sql "SELECT count(*) FROM incident_service.incidents WHERE rule_key = 'ORDER_RECOVERY_STALLED' AND scope_type = 'ORDER' AND source_reference IN ($idList)")
    if ($remaining -ne 0) { throw 'Scoped detection test incident cleanup left order incidents behind' }
}

try {
    $successKey = "tf-det-$([guid]::NewGuid().ToString('N'))"
    $declineKey = "tf-det-$([guid]::NewGuid().ToString('N'))"
    $recoveryKey = "tf-det-$([guid]::NewGuid().ToString('N'))"
    $testKeys.Add($successKey); $testKeys.Add($declineKey); $testKeys.Add($recoveryKey)

    $healthyStart = [DateTimeOffset]::UtcNow
    $success = Invoke-DetectionRequest -Method Post -Path '/api/v1/orders' -Headers @{ 'Idempotency-Key' = $successKey } `
        -Body (@{ sku = $testSku; quantity = 1 } | ConvertTo-Json -Compress)
    if ($success.Status -ne 201 -or $success.Body.status -ne 'CONFIRMED') { throw 'Healthy order did not confirm' }
    $decline = Invoke-DetectionRequest -Method Post -Path '/api/v1/orders' `
        -Headers @{ 'Idempotency-Key' = $declineKey; 'X-TraceForge-Failure' = 'payment-decline' } `
        -Body (@{ sku = $testSku; quantity = 1 } | ConvertTo-Json -Compress)
    if ($decline.Status -ne 402 -or $decline.Body.status -ne 'FAILED' -or -not $decline.Body.inventoryReleased) {
        throw 'Fully compensated payment decline did not return its expected business outcome'
    }
    Wait-DetectionCycles -After $healthyStart -Count 2
    foreach ($orderId in @([string]$success.Body.id, [string]$decline.Body.id)) {
        if ((Get-OrderIncident -OrderId $orderId -Status 'OPEN').Count -gt 0 -or
            (Get-OrderIncident -OrderId $orderId -Status 'RESOLVED').Count -gt 0) {
            throw 'A healthy or fully compensated business outcome was incorrectly classified as an incident'
        }
    }
    Write-Host 'PASS: confirmed order and fully compensated payment decline produced no incidents'

    $recoveryStart = [DateTimeOffset]::UtcNow
    $recovery = Invoke-DetectionRequest -Method Post -Path '/api/v1/orders' `
        -Headers @{ 'Idempotency-Key' = $recoveryKey; 'X-TraceForge-Failure' = 'payment-decline-compensation-unavailable' } `
        -Body (@{ sku = $testSku; quantity = 1 } | ConvertTo-Json -Compress)
    if ($recovery.Status -ne 503 -or $recovery.Body.status -ne 'COMPENSATION_REQUIRED' -or $recovery.Body.inventoryReleased) {
        throw 'Controlled recovery failure did not remain visibly pending compensation'
    }
    $openIncident = Wait-OrderIncident -OrderId ([string]$recovery.Body.id) -Status 'OPEN'
    Wait-DetectionCycles -After $recoveryStart -Count 2
    $deduplicated = Invoke-DetectionRequest -Method Get -Path "/api/v1/incidents/$($openIncident.id)"
    if ($deduplicated.Status -ne 200 -or $deduplicated.Body.id -ne $openIncident.id -or $deduplicated.Body.occurrenceCount -lt 2) {
        throw 'Repeated observations did not update the same open incident episode'
    }
    Write-Host "PASS: stalled compensation opened one incident episode $($openIncident.id)"

    $beforeRestart = Invoke-DetectionRequest -Method Get -Path '/api/v1/detection-status'
    if ($beforeRestart.Status -ne 200) { throw 'Detection status was unavailable before the restart check' }
    $orderSourceBeforeRestart = @($beforeRestart.Body.sources | Where-Object { $_.source -eq 'order-attention' } | Select-Object -First 1)
    if ($orderSourceBeforeRestart.Count -ne 1 -or $null -eq $orderSourceBeforeRestart[0].lastSuccessAt) {
        throw 'Order source freshness was not persisted before the restart check'
    }
    $lastOrderSuccessBeforeRestart = [DateTimeOffset]$orderSourceBeforeRestart[0].lastSuccessAt
    $orderStopped = $true
    & docker compose stop order-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop order-service to hold the recovery case open during the restart check' }
    $investigationRestartRequired = $true
    $investigationRestartAt = [DateTimeOffset]::UtcNow
    & docker compose restart investigation-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart investigation-service for the persistence check' }
    & docker compose up -d --wait investigation-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'investigation-service did not become healthy after restart' }
    $afterRestartIncident = Invoke-DetectionRequest -Method Get -Path "/api/v1/incidents/$($openIncident.id)"
    $afterRestartStatus = Invoke-DetectionRequest -Method Get -Path '/api/v1/detection-status'
    if ($afterRestartIncident.Status -ne 200 -or $afterRestartIncident.Body.id -ne $openIncident.id -or $afterRestartIncident.Body.status -ne 'OPEN') {
        throw 'The open incident did not survive investigation-service restart'
    }
    if ($afterRestartStatus.Status -ne 200) { throw 'Detection status was unavailable after investigation-service restart' }
    $orderSourceAfterRestart = @($afterRestartStatus.Body.sources | Where-Object { $_.source -eq 'order-attention' } | Select-Object -First 1)
    if ($orderSourceAfterRestart.Count -ne 1 -or $null -eq $orderSourceAfterRestart[0].lastSuccessAt -or
        ([DateTimeOffset]$orderSourceAfterRestart[0].lastSuccessAt) -lt $lastOrderSuccessBeforeRestart) {
        throw 'Persisted Order source freshness was missing or regressed after investigation-service restart'
    }
    Wait-DetectionCycles -After $investigationRestartAt -Count 2
    $staleOrderIncident = Invoke-DetectionRequest -Method Get -Path "/api/v1/incidents/$($openIncident.id)"
    $failedOrderSourceStatus = Invoke-DetectionRequest -Method Get -Path '/api/v1/detection-status'
    if ($staleOrderIncident.Status -ne 200 -or $staleOrderIncident.Body.status -ne 'OPEN' -or
        $failedOrderSourceStatus.Status -ne 200) {
        throw 'An unavailable Order source incorrectly resolved the existing recovery incident'
    }
    $failedOrderSource = @($failedOrderSourceStatus.Body.sources | Where-Object { $_.source -eq 'order-attention' } | Select-Object -First 1)
    if ($failedOrderSource.Count -ne 1 -or $failedOrderSource[0].status -notin @('UNAVAILABLE', 'STALE') -or
        $failedOrderSource[0].errorCode -ne 'UPSTREAM_UNAVAILABLE' -or
        ([DateTimeOffset]$failedOrderSource[0].lastSuccessAt) -lt $lastOrderSuccessBeforeRestart) {
        throw 'Order source outage did not preserve its last successful observation time'
    }
    $orderHealthPage = Invoke-DetectionRequest -Method Get -Path '/api/v1/incidents?status=OPEN&limit=100'
    if ($orderHealthPage.Status -ne 200) { throw 'Could not list the Order service health incident during its outage' }
    $orderServiceIncident = @($orderHealthPage.Body.items | Where-Object {
        $_.ruleKey -eq 'SERVICE_NOT_READY' -and $_.sourceReference -eq 'order-service'
    } | Select-Object -First 1)
    if ($orderServiceIncident.Count -ne 1) { throw 'Two failed Order health probes did not open a service incident' }
    $orderServiceIncident = $orderServiceIncident[0]
    & docker compose up -d --wait order-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'order-service did not become healthy after the persistence check' }
    $orderStopped = $false
    $healthDeadline = [DateTimeOffset]::UtcNow.AddSeconds(35)
    do {
        $resolvedPage = Invoke-DetectionRequest -Method Get -Path '/api/v1/incidents?status=RESOLVED&limit=100'
        if ($resolvedPage.Status -eq 200) {
            $resolvedOrderHealth = @($resolvedPage.Body.items | Where-Object { $_.id -eq $orderServiceIncident.id } | Select-Object -First 1)
            if ($resolvedOrderHealth.Count -gt 0) { break }
        }
        Start-Sleep -Seconds 1
    } while ([DateTimeOffset]::UtcNow -lt $healthDeadline)
    if ($resolvedOrderHealth.Count -eq 0) { throw 'Two healthy Order probes did not resolve the service incident' }
    Write-Host 'PASS: failed Order source did not resolve its incident; persisted freshness survived restart and two healthy probes resolved the service incident'
    $investigationRestartRequired = $false

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(35)
    do {
        $order = Invoke-DetectionRequest -Method Get -Path "/api/v1/orders/$($recovery.Body.id)"
        if ($order.Status -eq 200 -and $order.Body.status -eq 'FAILED' -and $order.Body.inventoryReleased) { break }
        Start-Sleep -Seconds 1
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    if ($order.Status -ne 200 -or $order.Body.status -ne 'FAILED' -or -not $order.Body.inventoryReleased) {
        throw 'Scheduled saga recovery did not complete compensation within the bounded deadline'
    }
    $resolvedIncident = Wait-OrderIncident -OrderId ([string]$recovery.Body.id) -Status 'RESOLVED' -TimeoutSeconds 30
    if ($resolvedIncident.id -ne $openIncident.id) { throw 'Resolution did not close the original incident episode' }
    Write-Host 'PASS: explicit terminal Order state with completed compensation resolved the original incident'

    $outageStart = [DateTimeOffset]::UtcNow
    $inventoryStopped = $true
    & docker compose stop inventory-service | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop inventory-service for the controlled health probe test' }
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(35)
    $serviceIncident = $null
    do {
        $page = Invoke-DetectionRequest -Method Get -Path '/api/v1/incidents?status=OPEN&limit=100'
        if ($page.Status -ne 200) { throw "Incident list returned HTTP $($page.Status) during outage test" }
        $serviceIncident = @($page.Body.items | Where-Object { $_.ruleKey -eq 'SERVICE_NOT_READY' -and $_.sourceReference -eq 'inventory-service' } | Select-Object -First 1)
        if ($serviceIncident.Count -gt 0) { $serviceIncident = $serviceIncident[0]; break }
        Start-Sleep -Seconds 1
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    if ($null -eq $serviceIncident) { throw 'Repeated failed health probes did not open the inventory service incident' }
    Write-Host "PASS: two or more failed health observations opened service incident $($serviceIncident.id)"

    $collectorTestStart = [DateTimeOffset]::UtcNow
    $collectorStopped = $true
    & docker compose stop otel-collector | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the Collector for the telemetry-independence check' }
    Wait-DetectionCycles -After $collectorTestStart -Count 2
    $telemetryIndependent = Invoke-DetectionRequest -Method Get -Path '/api/v1/detection-status'
    if ($telemetryIndependent.Status -ne 200 -or $telemetryIndependent.Body.latestCycle.status -ne 'COMPLETE') {
        throw 'Detection did not complete while the optional OpenTelemetry Collector was unavailable'
    }
    Write-Host 'PASS: deterministic detection completed with the optional Collector stopped'
} finally {
    $restoreErrors = [System.Collections.Generic.List[string]]::new()
    if ($collectorStopped) {
        try {
            & docker compose start otel-collector | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not restore the OpenTelemetry Collector' }
            & docker compose up -d --wait otel-collector | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'OpenTelemetry Collector did not become healthy after restoration' }
        } catch {
            $restoreErrors.Add($_.Exception.Message)
        }
    }
    if ($inventoryStopped) {
        try {
            & docker compose start inventory-service | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not restore inventory-service after the controlled outage' }
            & docker compose up -d --wait inventory-service | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'inventory-service did not become healthy after restoration' }
            if ($null -ne $serviceIncident) {
                $deadline = [DateTimeOffset]::UtcNow.AddSeconds(35)
                do {
                    $page = Invoke-DetectionRequest -Method Get -Path '/api/v1/incidents?status=RESOLVED&limit=100'
                    if ($page.Status -eq 200) {
                        $restored = @($page.Body.items | Where-Object { $_.id -eq $serviceIncident.id } | Select-Object -First 1)
                        if ($restored.Count -gt 0) { break }
                    }
                    Start-Sleep -Seconds 1
                } while ([DateTimeOffset]::UtcNow -lt $deadline)
                if ($restored.Count -eq 0) { throw 'Two healthy probes did not resolve the inventory service incident' }
                Write-Host 'PASS: two or more healthy probes resolved the inventory service incident'
            }
        } catch {
            $restoreErrors.Add($_.Exception.Message)
        }
    }
    if ($orderStopped) {
        try {
            & docker compose up -d --wait order-service | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'order-service could not be restored to healthy state' }
        } catch {
            $restoreErrors.Add($_.Exception.Message)
        }
    }
    if ($investigationRestartRequired) {
        try {
            & docker compose up -d --wait investigation-service | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'investigation-service could not be restored to healthy state' }
        } catch {
            $restoreErrors.Add($_.Exception.Message)
        }
    }
    try {
        Remove-DetectionTestIncidents -IdempotencyKeys $testKeys.ToArray()
        Remove-TraceForgeTestData -IdempotencyKeys $testKeys.ToArray() -Skus @($testSku)
    } catch {
        $restoreErrors.Add("Scoped test-data cleanup failed: $($_.Exception.Message)")
    }
    if ($restoreErrors.Count -gt 0) {
        throw ($restoreErrors -join '; ')
    }
}
