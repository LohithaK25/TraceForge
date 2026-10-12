$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$mavenImage = 'maven:3.9.16-eclipse-temurin-21'
$mavenCacheVolume = 'traceforge-maven-cache'
$services = @(
    [pscustomobject]@{ Name = 'api-gateway'; Schema = 'inventory_service' },
    [pscustomobject]@{ Name = 'inventory-service'; Schema = 'inventory_service' },
    [pscustomobject]@{ Name = 'payment-service'; Schema = 'payment_service' },
    [pscustomobject]@{ Name = 'order-service'; Schema = 'order_service' }
)

Write-Host 'Building and starting the complete local service stack'
& docker compose up --build -d --wait
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$composeJson = & docker compose config --format json
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
$composeConfig = ($composeJson -join "`n") | ConvertFrom-Json
$database = $composeConfig.services.postgres.environment
$databaseUrlBase = "jdbc:postgresql://postgres:5432/$($database.POSTGRES_DB)"

foreach ($service in $services) {
    $servicePath = (Resolve-Path (Join-Path $repoRoot "services/$($service.Name)")).Path.Replace('\', '/')
    $sourceMount = "type=bind,source=$servicePath,target=/workspace"
    $databaseUrl = "$databaseUrlBase`?currentSchema=$($service.Schema)"
    Write-Host "Running $($service.Name) tests with $mavenImage"
    $dockerArgs = @(
        'run', '--rm', '--network', 'traceforge-network',
        '--mount', $sourceMount,
        '--mount', "type=volume,source=$mavenCacheVolume,target=/root/.m2",
        '--workdir', '/workspace',
        '-e', 'SPRING_PROFILES_ACTIVE=local',
        '-e', "TRACEFORGE_DATABASE_URL=$databaseUrl",
        '-e', "POSTGRES_DB=$($database.POSTGRES_DB)",
        '-e', "POSTGRES_USER=$($database.POSTGRES_USER)",
        '-e', "POSTGRES_PASSWORD=$($database.POSTGRES_PASSWORD)",
        '-e', 'INVENTORY_SERVICE_URL=http://inventory-service:8081',
        '-e', 'PAYMENT_SERVICE_URL=http://payment-service:8083',
        $mavenImage, 'mvn', '-B', 'test'
    )
    & docker @dockerArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Write-Host 'Running live HTTP recovery and restart assertions'
& (Join-Path $PSScriptRoot 'verify-saga-recovery.ps1')
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host 'Running live OpenTelemetry propagation and Tempo trace assertions'
& (Join-Path $PSScriptRoot 'verify-traces.ps1')
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host 'Running live deterministic incident detection assertions'
& (Join-Path $PSScriptRoot 'verify-detection.ps1')
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
