function Invoke-TraceForgePostgresSql {
    param([Parameter(Mandatory)] [string] $Sql)

    $composeJson = & docker compose config --format json
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the resolved Compose database settings' }
    $composeConfig = ($composeJson -join "`n") | ConvertFrom-Json
    $database = $composeConfig.services.postgres.environment
    $arguments = @(
        'compose', 'exec', '-T', 'postgres', 'psql',
        '-U', [string] $database.POSTGRES_USER,
        '-d', [string] $database.POSTGRES_DB,
        '-v', 'ON_ERROR_STOP=1', '-A', '-t', '-c', $Sql
    )
    $result = & docker @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Scoped TraceForge test-data database operation failed' }
    return ($result -join "`n").Trim()
}

function New-TraceForgeTestSku {
    param(
        [Parameter(Mandatory)] [ValidatePattern('^[A-Z0-9]{2,8}$')] [string] $Prefix,
        [Parameter(Mandatory)] [ValidateRange(1, 1000000)] [int] $Quantity
    )

    $sku = "TF-$Prefix-$([guid]::NewGuid().ToString('N').Substring(0, 8).ToUpperInvariant())"
    [void] (Invoke-TraceForgePostgresSql -Sql "INSERT INTO inventory_service.inventory_items (sku, available_quantity) VALUES ('$sku', $Quantity)")
    return $sku
}

function Remove-TraceForgeTestData {
    param(
        [string[]] $IdempotencyKeys = @(),
        [string[]] $Skus = @()
    )

    $keys = @($IdempotencyKeys | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    $skuValues = @($Skus | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    foreach ($key in $keys) {
        if ($key -notmatch '^[A-Za-z0-9-]{1,128}$') { throw 'Refusing to clean an unrecognized test idempotency key' }
    }
    foreach ($sku in $skuValues) {
        if ($sku -notmatch '^TF-[A-Z0-9]{2,8}-[A-F0-9]{8}$') { throw 'Refusing to clean an unrecognized test SKU' }
    }
    if ($keys.Count -eq 0 -and $skuValues.Count -eq 0) { return }

    $keyList = ($keys | ForEach-Object { "'$_'" }) -join ', '
    $skuList = ($skuValues | ForEach-Object { "'$_'" }) -join ', '
    $orderScope = if ($keys.Count -gt 0) { "idempotency_key IN ($keyList)" } else { 'FALSE' }
    $skuScope = if ($skuValues.Count -gt 0) { "sku IN ($skuList)" } else { 'FALSE' }
    $orderIds = if ($keys.Count -gt 0) { 'SELECT id FROM order_service.orders WHERE ' + $orderScope } else { 'SELECT NULL::uuid WHERE FALSE' }
    $statements = @(
        "DELETE FROM payment_service.payment_attempts WHERE idempotency_key IN ($keyList) OR order_id IN ($orderIds)",
        "DELETE FROM inventory_service.inventory_reservations WHERE order_id IN ($orderIds) OR $skuScope",
        "DELETE FROM order_service.orders WHERE $orderScope",
        "DELETE FROM inventory_service.inventory_items WHERE $skuScope"
    )
    foreach ($statement in $statements) {
        if ($statement.Contains('IN ()')) { continue }
        [void] (Invoke-TraceForgePostgresSql -Sql $statement)
    }

    $remainingOrders = [int] (Invoke-TraceForgePostgresSql -Sql "SELECT count(*) FROM order_service.orders WHERE $orderScope")
    $remainingPayments = if ($keys.Count -gt 0) {
        [int] (Invoke-TraceForgePostgresSql -Sql "SELECT count(*) FROM payment_service.payment_attempts WHERE idempotency_key IN ($keyList) OR order_id IN ($orderIds)")
    } else { 0 }
    $remainingReservations = [int] (Invoke-TraceForgePostgresSql -Sql "SELECT count(*) FROM inventory_service.inventory_reservations WHERE order_id IN ($orderIds) OR $skuScope")
    $remainingSkus = [int] (Invoke-TraceForgePostgresSql -Sql "SELECT count(*) FROM inventory_service.inventory_items WHERE $skuScope")
    if ($remainingOrders -ne 0 -or $remainingPayments -ne 0 -or $remainingReservations -ne 0 -or $remainingSkus -ne 0) {
        throw 'Scoped TraceForge test-data cleanup left order, payment, reservation, or inventory rows behind'
    }
}
