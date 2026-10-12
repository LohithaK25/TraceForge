$ErrorActionPreference = 'Stop'

$gatewayUrl = 'http://localhost:8080'
$tempoUrl = 'http://localhost:3200'
$traceWaitSeconds = 45
. (Join-Path $PSScriptRoot 'TraceForgeTestData.ps1')
$traceTestSku = New-TraceForgeTestSku -Prefix 'OTEL' -Quantity 100
$testOrderKeys = [System.Collections.Generic.List[string]]::new()

function New-TraceParent {
    $traceId = [guid]::NewGuid().ToString('N')
    $parentSpanId = [guid]::NewGuid().ToString('N').Substring(0, 16)
    return [pscustomobject]@{
        TraceId = $traceId
        ParentSpanId = $parentSpanId
        Header = "00-$traceId-$parentSpanId-01"
    }
}

function Invoke-TraceForgeRequest {
    param(
        [Parameter(Mandatory)] [string] $Method,
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [hashtable] $Headers,
        [string] $Body
    )

    $arguments = @{
        Uri = "$gatewayUrl$Path"
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

function Get-AttributeValue {
    param($Attributes, [string] $Key)
    foreach ($attribute in @($Attributes)) {
        if ($attribute.key -ne $Key) { continue }
        $value = $attribute.value
        foreach ($propertyName in @('stringValue', 'intValue', 'boolValue', 'doubleValue', 'arrayValue', 'kvlistValue')) {
            $property = $value.PSObject.Properties[$propertyName]
            if ($null -ne $property) { return $property.Value }
        }
        if ($null -ne $value) { return $value }
    }
    return $null
}

function Convert-TempoIdToHex {
    param([string] $Value)

    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    if ($Value -match '^(?:[0-9a-fA-F]{16}|[0-9a-fA-F]{32})$') {
        return $Value.ToLowerInvariant()
    }
    try {
        $bytes = [Convert]::FromBase64String($Value)
        if ($bytes.Length -notin @(8, 16)) { return $Value.ToLowerInvariant() }
        return (-join ($bytes | ForEach-Object { $_.ToString('x2') }))
    } catch {
        return $Value.ToLowerInvariant()
    }
}

function Convert-TempoTraceToSpanRows {
    param($Document)

    $trace = if ($null -ne $Document.trace) { $Document.trace } else { $Document }
    $rows = [System.Collections.Generic.List[object]]::new()

    foreach ($resourceSpan in @($trace.resourceSpans)) {
        $serviceName = Get-AttributeValue $resourceSpan.resource.attributes 'service.name'
        foreach ($scopeSpan in @($resourceSpan.scopeSpans)) {
            foreach ($span in @($scopeSpan.spans)) {
                $rows.Add([pscustomobject]@{ Service = [string] $serviceName; Span = $span })
            }
        }
    }

    # Tempo's legacy OTLP JSON representation uses batches rather than resourceSpans.
    foreach ($batch in @($trace.batches)) {
        $serviceName = Get-AttributeValue $batch.resource.attributes 'service.name'
        $groups = if ($batch.scopeSpans) { @($batch.scopeSpans) } else { @($batch) }
        foreach ($group in $groups) {
            foreach ($span in @($group.spans)) {
                $rows.Add([pscustomobject]@{ Service = [string] $serviceName; Span = $span })
            }
        }
    }
    return $rows.ToArray()
}

function Get-TempoTrace {
    param([string] $TraceId)
    try {
        $response = Invoke-WebRequest -Uri "$tempoUrl/api/v2/traces/$TraceId" -UseBasicParsing `
            -SkipHttpErrorCheck -TimeoutSec 5
        if ([int] $response.StatusCode -ne 200) { return $null }
        return ($response.Content | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Wait-ForTrace {
    param([string] $TraceId, [string[]] $ExpectedServices)

    $deadline = (Get-Date).AddSeconds($traceWaitSeconds)
    do {
        $document = Get-TempoTrace $TraceId
        if ($null -ne $document) {
            $spans = @(Convert-TempoTraceToSpanRows $document)
            $services = @($spans | ForEach-Object Service | Sort-Object -Unique)
            $missing = @($ExpectedServices | Where-Object { $_ -notin $services })
            $wrongTrace = @($spans | Where-Object {
                (Convert-TempoIdToHex ([string] $_.Span.traceId)) -ne $TraceId.ToLowerInvariant()
            })
            if ($spans.Count -gt 0 -and $missing.Count -eq 0 -and $wrongTrace.Count -eq 0) {
                return [pscustomobject]@{ Document = $document; Spans = $spans }
            }
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    throw "Tempo did not return trace $TraceId with services [$($ExpectedServices -join ', ')] within $traceWaitSeconds seconds"
}

function Assert-OrderOperation {
    param($Trace, [string] $SpanName, [string] $Attribute, [string] $Expected)
    $match = @($Trace.Spans | Where-Object {
        $_.Service -eq 'order-service' -and $_.Span.name -eq $SpanName -and
        (Get-AttributeValue $_.Span.attributes $Attribute) -eq $Expected
    })
    if ($match.Count -eq 0) {
        throw "Trace is missing $SpanName with $Attribute=$Expected"
    }
    return $match[0].Span
}

function Assert-OperationAttribute {
    param($Trace, [string] $Service, [string] $SpanName, [string] $Attribute, [string] $Expected)
    $match = @($Trace.Spans | Where-Object {
        $_.Service -eq $Service -and $_.Span.name -eq $SpanName -and
        [string](Get-AttributeValue $_.Span.attributes $Attribute) -eq $Expected
    })
    if ($match.Count -eq 0) {
        throw "Trace is missing $Service/$SpanName with $Attribute=$Expected"
    }
}

function Get-RecordedSpanStatus {
    param($Span)

    $code = if ($null -ne $Span.status -and $null -ne $Span.status.code) { [string] $Span.status.code } else { '' }
    if ($code -in @('1', 'OK', 'STATUS_CODE_OK')) { return 'OK' }
    if ($code -in @('2', 'ERROR', 'STATUS_CODE_ERROR')) { return 'ERROR' }
    return 'UNSET'
}

function Assert-PaymentSpanStatus {
    param($Trace, [string] $Outcome, [string] $ExpectedStatus)

    $match = @($Trace.Spans | Where-Object {
        $_.Service -eq 'payment-service' -and $_.Span.name -eq 'payment.authorize' -and
        (Get-AttributeValue $_.Span.attributes 'payment.outcome') -eq $Outcome
    }) | Select-Object -First 1
    if ($null -eq $match) { throw "Trace is missing payment.authorize with payment.outcome=$Outcome" }
    $actualStatus = Get-RecordedSpanStatus $match.Span
    if ($actualStatus -ne $ExpectedStatus) {
        throw "payment.authorize for outcome '$Outcome' had exported span status '$actualStatus'; expected '$ExpectedStatus'"
    }
}

function New-Order {
    param([string] $Sku, [hashtable] $Headers)
    $key = "otel-check-$([guid]::NewGuid())"
    $testOrderKeys.Add($key)
    $Headers['Idempotency-Key'] = $key
    return Invoke-TraceForgeRequest -Method Post -Path '/api/v1/orders' -Headers $Headers `
        -Body (@{ sku = $Sku; quantity = 1 } | ConvertTo-Json -Compress)
}

Write-Host 'Checking trace pipeline endpoints'
try {
$health = Invoke-WebRequest -Uri "$tempoUrl/ready" -UseBasicParsing -TimeoutSec 5
if ([int] $health.StatusCode -ne 200) { throw "Tempo readiness returned HTTP $($health.StatusCode)" }

$successParent = New-TraceParent
$success = New-Order $traceTestSku @{ traceparent = $successParent.Header }
if ($success.Status -ne 201 -or $success.Body.status -ne 'CONFIRMED') {
    throw "Successful trace scenario returned HTTP $($success.Status): $($success.Body | ConvertTo-Json -Compress)"
}
$successTrace = Wait-ForTrace $successParent.TraceId @('api-gateway', 'order-service', 'inventory-service', 'payment-service')
$gatewaySpan = @($successTrace.Spans | Where-Object {
    $_.Service -eq 'api-gateway' -and
        (Convert-TempoIdToHex ([string] $_.Span.parentSpanId)) -eq $successParent.ParentSpanId
}) | Select-Object -First 1
if ($null -eq $gatewaySpan -or
        (Convert-TempoIdToHex ([string] $gatewaySpan.Span.parentSpanId)) -ne $successParent.ParentSpanId) {
    throw 'The gateway server span did not retain the caller-supplied W3C parent span ID'
}
Assert-PaymentSpanStatus $successTrace 'authorized' 'OK'
Write-Host "PASS: confirmed order trace $($successParent.TraceId) correlates Gateway, Order, Inventory, and Payment with the caller traceparent"
Write-Host 'PASS: exported payment.authorize span for the successful order has OK status'

$inventoryParent = New-TraceParent
$inventoryFailure = New-Order 'SKU-NOT-FOUND-OTEL' @{ traceparent = $inventoryParent.Header }
if ($inventoryFailure.Status -ne 404 -or $inventoryFailure.Body.failureReason -ne 'UNKNOWN_SKU') {
    throw "Unknown-SKU scenario returned unexpected result: $($inventoryFailure.Status) / $($inventoryFailure.Body | ConvertTo-Json -Compress)"
}
$inventoryTrace = Wait-ForTrace $inventoryParent.TraceId @('api-gateway', 'order-service', 'inventory-service')
$inventoryOrderSpan = Assert-OrderOperation $inventoryTrace 'order.create' 'order.failure.reason' 'UNKNOWN_SKU'
Assert-OperationAttribute $inventoryTrace 'inventory-service' 'inventory.reserve' 'http.response.status_code' '404'
if ((Convert-TempoIdToHex ([string] $inventoryOrderSpan.traceId)) -ne $inventoryParent.TraceId) {
    throw 'Inventory rejection escaped the known trace ID'
}
Write-Host "PASS: unknown-SKU trace $($inventoryParent.TraceId) contains HTTP 404 and UNKNOWN_SKU failure evidence"

$declineParent = New-TraceParent
$decline = New-Order $traceTestSku @{
    traceparent = $declineParent.Header
    'X-TraceForge-Failure' = 'payment-decline'
}
if ($decline.Status -ne 402 -or $decline.Body.failureReason -ne 'PAYMENT_DECLINED' -or -not $decline.Body.inventoryReleased) {
    throw "Decline scenario returned unexpected result: $($decline.Status) / $($decline.Body | ConvertTo-Json -Compress)"
}
$declineTrace = Wait-ForTrace $declineParent.TraceId @('api-gateway', 'order-service', 'inventory-service', 'payment-service')
Assert-OrderOperation $declineTrace 'order.create' 'order.failure.reason' 'PAYMENT_DECLINED' | Out-Null
Assert-OperationAttribute $declineTrace 'payment-service' 'payment.authorize' 'payment.outcome' 'declined'
Assert-PaymentSpanStatus $declineTrace 'declined' 'ERROR'
Assert-OperationAttribute $declineTrace 'inventory-service' 'inventory.release' 'inventory.outcome' 'released'
Write-Host "PASS: payment-decline trace $($declineParent.TraceId) contains an ERROR payment span and inventory compensation span"

$outageParent = New-TraceParent
$outage = New-Order $traceTestSku @{
    traceparent = $outageParent.Header
    'X-TraceForge-Failure' = 'payment-unavailable'
}
if ($outage.Status -ne 503 -or $outage.Body.status -ne 'INVENTORY_RESERVED') {
    throw "Payment outage did not preserve the reserved-but-unconfirmed state: $($outage.Status) / $($outage.Body | ConvertTo-Json -Compress)"
}
$outageTrace = Wait-ForTrace $outageParent.TraceId @('api-gateway', 'order-service', 'inventory-service', 'payment-service')
$originOrderSpan = Assert-OrderOperation $outageTrace 'order.create' 'order.id' ([string] $outage.Body.id)
Assert-OperationAttribute $outageTrace 'payment-service' 'payment.authorize' 'http.response.status_code' '503'
Assert-OrderOperation $outageTrace 'order.create' 'order.recovery.error' 'PAYMENT_RETRY_SCHEDULED' | Out-Null

$recoveryDeadline = (Get-Date).AddSeconds(60)
$recovered = $false
do {
    $read = Invoke-TraceForgeRequest -Method Get -Path "/api/v1/orders/$($outage.Body.id)" -Headers @{}
    if ($read.Status -eq 200 -and $read.Body.status -eq 'CONFIRMED') {
        $recovered = $true
        break
    }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $recoveryDeadline)
if (-not $recovered) { throw 'Scheduled recovery did not complete the controlled payment outage within 60 seconds' }

$recoveryLinked = $false
$searchDeadline = (Get-Date).AddSeconds(45)
do {
    try {
        $tagQuery = [uri]::EscapeDataString("order.id=$($outage.Body.id)")
        $search = Invoke-RestMethod -Uri "$tempoUrl/api/search?tags=$tagQuery&limit=100" -TimeoutSec 5
        foreach ($candidate in @($search.traces)) {
            if ($candidate.traceID -eq $outageParent.TraceId) { continue }
            $candidateDocument = Get-TempoTrace ([string] $candidate.traceID)
            if ($null -eq $candidateDocument) { continue }
            $candidateSpans = @(Convert-TempoTraceToSpanRows $candidateDocument)
            $workerSpans = @($candidateSpans | Where-Object {
                $_.Service -eq 'order-service' -and $_.Span.name -eq 'order.recovery.worker' -and
                (Get-AttributeValue $_.Span.attributes 'order.id') -eq [string] $outage.Body.id
            })
            foreach ($workerSpan in $workerSpans) {
                $links = @($workerSpan.Span.links)
                if (@($links | Where-Object {
                    (Convert-TempoIdToHex ([string] $_.traceId)) -eq $outageParent.TraceId -and
                        (Convert-TempoIdToHex ([string] $_.spanId)) -eq
                        (Convert-TempoIdToHex ([string] $originOrderSpan.spanId))
                }).Count -gt 0) {
                    $recoveryLinked = $true
                    break
                }
            }
            if ($recoveryLinked) { break }
        }
    } catch {
        # Keep polling the backend's bounded, eventually consistent search index.
    }
    if (-not $recoveryLinked) { Start-Sleep -Milliseconds 500 }
} while (-not $recoveryLinked -and (Get-Date) -lt $searchDeadline)

if (-not $recoveryLinked) {
    throw "Recovery trace was not found with a link to origin trace $($outageParent.TraceId) span $($originOrderSpan.spanId)"
}
Write-Host "PASS: payment outage trace $($outageParent.TraceId) is distinct from the scheduled recovery trace, which links to the original order span"

Write-Host 'Checking business behavior while the telemetry Collector is unavailable'
try {
    & docker compose stop otel-collector | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the local Collector for the telemetry-outage check' }
    $telemetryOutage = New-Order $traceTestSku @{
        traceparent = (New-TraceParent).Header
        'X-TraceForge-Failure' = 'payment-decline'
    }
    if (($telemetryOutage.Status -ne 402) -or
            ($telemetryOutage.Body.failureReason -ne 'PAYMENT_DECLINED') -or
            (-not $telemetryOutage.Body.inventoryReleased)) {
        throw "Business outcome changed while telemetry was unavailable: HTTP $($telemetryOutage.Status) / $($telemetryOutage.Body | ConvertTo-Json -Compress)"
    }
} finally {
    & docker compose up -d --wait --wait-timeout 45 otel-collector | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restore the local Collector after the telemetry-outage check' }
}
Write-Host 'PASS: a payment decline remained HTTP 402 with confirmed inventory compensation while Collector was stopped'

Write-Host 'All end-to-end trace assertions passed against Tempo-exported traces.'
} finally {
    Remove-TraceForgeTestData -IdempotencyKeys $testOrderKeys.ToArray() -Skus @($traceTestSku)
}
