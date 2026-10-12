[CmdletBinding()]
param(
    [switch] $PrepareOnly,
    [switch] $RunOutages,
    [ValidatePattern('^traceforge-p7out-[0-9a-f]{10}$')]
    [string] $CleanupProject
)

$ErrorActionPreference = 'Stop'

$selectedModes = @()
if ($PrepareOnly) { $selectedModes += 'prepare' }
if ($RunOutages) { $selectedModes += 'run' }
if (-not [string]::IsNullOrWhiteSpace($CleanupProject)) { $selectedModes += 'cleanup' }
if ($selectedModes.Count -gt 1) {
    throw 'Choose only one of -PrepareOnly, -RunOutages, or -CleanupProject.'
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$templatePath = Join-Path $PSScriptRoot 'phase7-outage.compose.template.yaml'
$manifestPath = Join-Path $env:TEMP 'traceforge-phase7-outage.compose.yaml'
$testServices = @(
    'tempo', 'otel-collector', 'postgres', 'inventory-service',
    'payment-service', 'order-service', 'investigation-service', 'api-gateway'
)
$mutableDependencies = @(
    'postgres', 'tempo', 'inventory-service', 'order-service',
    'investigation-service', 'otel-collector'
)
$builtServiceNames = @(
    'tempo', 'otel-collector', 'inventory-service', 'payment-service',
    'order-service', 'investigation-service', 'api-gateway'
)
$builtImageNames = @{
    'tempo' = 'tempo'
    'otel-collector' = 'otel-collector'
    'inventory-service' = 'inventory'
    'payment-service' = 'payment'
    'order-service' = 'order'
    'investigation-service' = 'investigation'
    'api-gateway' = 'gateway'
}
$loopbackBase = 'http://127.0.0.1:18080'
$investigationBase = 'http://127.0.0.1:18090'

function Get-RenderedManifest {
    $rootForYaml = $repoRoot.Replace('\', '/')
    $template = Get-Content -LiteralPath $templatePath -Raw
    if (-not $template.Contains('__TRACEFORGE_ROOT__')) {
        throw 'The outage Compose template has no project-root placeholder.'
    }
    return $template.Replace('__TRACEFORGE_ROOT__', $rootForYaml)
}

function Ensure-Manifest {
    $rendered = Get-RenderedManifest
    if (Test-Path -LiteralPath $manifestPath) {
        $existing = Get-Content -LiteralPath $manifestPath -Raw
        if ($existing -cne $rendered) {
            throw "Refusing to overwrite the existing temporary manifest at $manifestPath. Inspect or move it yourself before retrying."
        }
        return
    }
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($manifestPath, $rendered, $encoding)
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory)] [string[]] $Arguments,
        [switch] $RequiresEngine,
        [Parameter(Mandatory)] [string] $ProjectName
    )

    $dockerArguments = @()
    if ($RequiresEngine) {
        $dockerArguments += @('--context', 'desktop-linux')
    }
    $dockerArguments += @(
        'compose', '--project-name', $ProjectName,
        '--project-directory', $env:TEMP,
        '--file', $manifestPath
    )
    $dockerArguments += $Arguments
    $output = & docker @dockerArguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "docker $($dockerArguments -join ' ') failed with exit code $exitCode."
    }
    return $output
}

function Assert-ResolvedIsolation {
    param(
        [Parameter(Mandatory)] [string] $ProjectName,
        [Parameter(Mandatory)] $Resolved
    )

    $expectedServices = @(
        'tempo', 'otel-collector', 'postgres', 'inventory-service',
        'payment-service', 'order-service', 'investigation-service', 'api-gateway'
    )
    $actualServices = @($Resolved.services.Keys | Sort-Object)
    $expectedSorted = @($expectedServices | Sort-Object)
    if (Compare-Object -ReferenceObject $expectedSorted -DifferenceObject $actualServices) {
        throw "Resolved services do not match the isolated outage set: $($actualServices -join ', ')."
    }

    $declaredVolumes = @()
    if ($null -ne $Resolved.volumes) { $declaredVolumes = @($Resolved.volumes.Keys) }
    if ($declaredVolumes.Count -ne 1 -or $declaredVolumes[0] -ne 'phase7-postgres-data') {
        throw 'The resolved outage manifest must declare only its isolated PostgreSQL data volume.'
    }
    $postgresVolume = $Resolved.volumes['phase7-postgres-data']
    if ($postgresVolume.external -eq $true -or
        [string]$postgresVolume.name -ne "traceforge-phase7-outage-postgres-$ProjectName") {
        throw 'The outage PostgreSQL volume is external or not uniquely named for this Compose project.'
    }
    foreach ($serviceName in $Resolved.services.Keys) {
        $service = $Resolved.services[$serviceName]
        if ($service.container_name) {
            throw "Service '$serviceName' has a fixed container name instead of a Compose project-scoped name."
        }
        if (@($service.networks.Keys | Where-Object { $_ -ne 'default' }).Count -gt 0) {
            throw "Service '$serviceName' is attached to a non-default network."
        }
        foreach ($mount in @($service.volumes)) {
            if ($mount.type -eq 'volume' -and
                ($serviceName -ne 'postgres' -or $mount.source -ne 'phase7-postgres-data' -or
                    $mount.target -ne '/var/lib/postgresql/data')) {
                throw "Service '$serviceName' has an unintended named-volume mount."
            }
            if ($mount.type -eq 'bind' -and -not $mount.read_only) {
                throw "Service '$serviceName' has a writable bind mount."
            }
        }
    }

    if (@($Resolved.services.postgres.volumes | ForEach-Object { $_.source }) -notcontains 'phase7-postgres-data') {
        throw 'Disposable PostgreSQL does not use its project-scoped persistence volume.'
    }
    $tempoTmpfsSpecs = @($Resolved.services.tempo.tmpfs | ForEach-Object { [string]$_ })
    $tempoTmpfsMounts = @($tempoTmpfsSpecs | ForEach-Object { ($_ -split ':', 2)[0] })
    if ($tempoTmpfsMounts -notcontains '/var/tempo') {
        throw 'Disposable Tempo storage is not tmpfs-backed.'
    }
    if ($tempoTmpfsSpecs -notcontains '/var/tempo:uid=10001,gid=10001,mode=0750') {
        throw 'Disposable Tempo tmpfs ownership does not match the non-root Tempo runtime user.'
    }

    if (-not $Resolved.ContainsKey('networks') -or -not $Resolved.networks.ContainsKey('default') -or
        @($Resolved.networks.Keys).Count -ne 1) {
        throw 'The Compose-generated default network is missing.'
    }
    $network = $Resolved.networks.default
    if ($network.external -eq $true) {
        throw 'The outage network must not be external.'
    }
    if ($network.name -eq 'traceforge-network') {
        throw 'The outage manifest resolves to the application project network.'
    }
    if ($network.name -and $network.name -ne "${ProjectName}_default") {
        throw "Unexpected network name '$($network.name)'; expected Compose project-scoped networking."
    }

    $expectedPorts = @{
        'api-gateway' = @{ published = '18080'; target = 8080 }
        'investigation-service' = @{ published = '18090'; target = 8090 }
    }
    foreach ($serviceName in $Resolved.services.Keys) {
        $configuredPorts = $Resolved.services[$serviceName].ports
        $ports = [System.Collections.Generic.List[object]]::new()
        if ($null -ne $configuredPorts) {
            foreach ($port in @($configuredPorts)) { [void]$ports.Add($port) }
        }
        if ($serviceName -notin $expectedPorts.Keys -and $ports.Count -gt 0) {
            throw "Service '$serviceName' unexpectedly publishes a host port."
        }
        if ($serviceName -in $expectedPorts.Keys) {
            if ($ports.Count -ne 1) {
                throw "Service '$serviceName' must publish exactly one loopback test port."
            }
            $expected = $expectedPorts[$serviceName]
            if ($ports[0].host_ip -ne '127.0.0.1' -or
                [string]$ports[0].published -ne $expected.published -or
                [int]$ports[0].target -ne $expected.target) {
                throw "Service '$serviceName' has an unexpected or non-loopback published port."
            }
        }
    }

    $builtServices = @($Resolved.services.Keys | Where-Object { $null -ne $Resolved.services[$_].build })
    $images = @($builtServices | ForEach-Object { [string]$Resolved.services[$_].image })
    $imagesOutsidePrefix = @($images | Where-Object { -not $_.StartsWith('traceforge-phase7-outage-') })
    if ($images.Count -ne $builtServices.Count -or $imagesOutsidePrefix.Count -gt 0) {
        throw 'A built service does not use a unique Phase 7 outage image name.'
    }
    if (Compare-Object -ReferenceObject @($builtServiceNames | Sort-Object) -DifferenceObject @($builtServices | Sort-Object)) {
        throw 'The built service set does not match the verified outage topology.'
    }
    if (@($images | Select-Object -Unique).Count -ne $images.Count) {
        throw 'Outage build image names are not unique.'
    }

    $allowedBindTargets = @(
        '/etc/tempo/tempo.yaml',
        '/etc/otelcol-contrib/config.yaml'
    )
    foreach ($serviceName in $Resolved.services.Keys) {
        foreach ($mount in @($Resolved.services[$serviceName].volumes)) {
            if ($mount.type -eq 'bind') {
                if ($mount.target -notin $allowedBindTargets) {
                    throw "Unexpected bind mount '$($mount.target)' in service '$serviceName'."
                }
                $expectedSource = switch ($mount.target) {
                    '/etc/tempo/tempo.yaml' { (Join-Path $repoRoot 'observability/tempo.yaml').Replace('\', '/') }
                    '/etc/otelcol-contrib/config.yaml' { (Join-Path $repoRoot 'observability/otel-collector.yaml').Replace('\', '/') }
                }
                if ($mount.source.Replace('\', '/') -ne $expectedSource) {
                    throw "Bind mount for '$($mount.target)' does not resolve to the repository's version-controlled configuration."
                }
            }
        }
    }
}

function Get-ResolvedConfig {
    param([Parameter(Mandatory)] [string] $ProjectName)
    $jsonLines = Invoke-Compose -ProjectName $ProjectName -Arguments @('config', '--format', 'json')
    $json = $jsonLines -join "`n"
    return ConvertFrom-Json -InputObject $json -AsHashtable
}

function Assert-RunImageNames {
    param([Parameter(Mandatory)] $Resolved, [Parameter(Mandatory)] [string] $ProjectName)
    foreach ($serviceName in $builtImageNames.Keys) {
        $imageName = $builtImageNames[$serviceName]
        if ([string]$Resolved.services[$serviceName].image -ne "traceforge-phase7-outage-${imageName}:$ProjectName") {
            throw "Service '$serviceName' did not resolve to the unique image for this test project."
        }
    }
}

function Invoke-Api {
    param(
        [Parameter(Mandatory)] [ValidateSet('GET', 'POST')] [string] $Method,
        [Parameter(Mandatory)] [string] $Path,
        [hashtable] $Headers = @{},
        [string] $Body,
        [string] $BaseUrl
    )

    if ([string]::IsNullOrWhiteSpace($BaseUrl)) { $BaseUrl = $loopbackBase }

    $request = @{
        Uri = "$BaseUrl$Path"
        Method = $Method
        Headers = $Headers
        SkipHttpErrorCheck = $true
        TimeoutSec = 15
    }
    if ($null -ne $Body) {
        $request.ContentType = 'application/json'
        $request.Body = $Body
    }
    $response = Invoke-WebRequest @request
    $payload = $null
    if (-not [string]::IsNullOrWhiteSpace($response.Content)) {
        try { $payload = ConvertFrom-Json -InputObject $response.Content }
        catch { $payload = $response.Content }
    }
    return [pscustomobject]@{
        Status = [int]$response.StatusCode
        Body = $payload
        Text = [string]$response.Content
    }
}

function Wait-Until {
    param(
        [Parameter(Mandatory)] [scriptblock] $Probe,
        [Parameter(Mandatory)] [string] $Description,
        [ValidateRange(1, 300)] [int] $TimeoutSeconds = 60
    )
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $value = & $Probe
            if ($null -ne $value -and ($value -isnot [bool] -or $value)) { return $value }
        } catch {
            # Startup and bounded outage windows are polled; only the deadline is fatal.
        }
        Start-Sleep -Seconds 1
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Description after $TimeoutSeconds seconds."
}

function Get-DetectionStatus {
    $response = Invoke-Api -Method GET -Path '/api/v1/detection-status'
    if ($response.Status -ne 200) { return $null }
    return $response.Body
}

function Get-Source {
    param([Parameter(Mandatory)] $Detection, [Parameter(Mandatory)] [string] $Name)
    $matches = @($Detection.sources | Where-Object { $_.source -eq $Name } | Select-Object -First 1)
    if ($matches.Count -eq 0) { return $null }
    return $matches[0]
}

function Get-ServiceSnapshot {
    param([Parameter(Mandatory)] $Detection, [Parameter(Mandatory)] [string] $Name)
    $matches = @($Detection.services | Where-Object { $_.serviceName -eq $Name } | Select-Object -First 1)
    if ($matches.Count -eq 0) { return $null }
    return $matches[0]
}

function Get-IncidentPage {
    param([Parameter(Mandatory)] [ValidateSet('OPEN', 'RESOLVED')] [string] $Status)
    $response = Invoke-Api -Method GET -Path "/api/v1/incidents?status=$Status&limit=100"
    if ($response.Status -ne 200) { throw "Incident list returned HTTP $($response.Status)." }
    return $response.Body
}

function Get-MatchingIncidents {
    param(
        [Parameter(Mandatory)] [ValidateSet('OPEN', 'RESOLVED')] [string] $Status,
        [Parameter(Mandatory)] [string] $RuleKey,
        [Parameter(Mandatory)] [string] $SourceReference
    )
    $page = Get-IncidentPage -Status $Status
    return @($page.items | Where-Object {
        $_.ruleKey -eq $RuleKey -and $_.sourceReference -eq $SourceReference
    })
}

function Find-Incident {
    param(
        [Parameter(Mandatory)] [ValidateSet('OPEN', 'RESOLVED')] [string] $Status,
        [Parameter(Mandatory)] [string] $RuleKey,
        [Parameter(Mandatory)] [string] $SourceReference
    )
    $matches = @(Get-MatchingIncidents -Status $Status -RuleKey $RuleKey -SourceReference $SourceReference)
    if ($matches.Count -eq 0) { return $null }
    return $matches[0]
}

function Get-Incident {
    param([Parameter(Mandatory)] [string] $Id)
    $response = Invoke-Api -Method GET -Path "/api/v1/incidents/$Id"
    if ($response.Status -ne 200) { throw "Incident $Id returned HTTP $($response.Status)." }
    return $response.Body
}

function Wait-ForCycleAfter {
    param([Parameter(Mandatory)] [string] $CycleId, [int] $TimeoutSeconds = 30)
    return Wait-Until -Description 'a new completed detection cycle' -TimeoutSeconds $TimeoutSeconds -Probe {
        $detection = Get-DetectionStatus
        if ($null -eq $detection -or $null -eq $detection.latestCycle) { return $null }
        if ($detection.latestCycle.cycleId -eq $CycleId -or $detection.latestCycle.status -eq 'RUNNING') { return $null }
        return $detection
    }
}

function Wait-ForIncident {
    param(
        [Parameter(Mandatory)] [ValidateSet('OPEN', 'RESOLVED')] [string] $Status,
        [Parameter(Mandatory)] [string] $RuleKey,
        [Parameter(Mandatory)] [string] $SourceReference,
        [int] $TimeoutSeconds = 60
    )
    return Wait-Until -Description "$Status $RuleKey incident for $SourceReference" -TimeoutSeconds $TimeoutSeconds -Probe {
        $incident = Find-Incident -Status $Status -RuleKey $RuleKey -SourceReference $SourceReference
        if ($null -eq $incident) { return $null }
        return $incident
    }
}

function Stop-TestDependency {
    param([Parameter(Mandatory)] [string] $Service)
    if ($Service -notin $mutableDependencies) {
        throw "Refusing to stop service '$Service'; it is not an approved disposable dependency."
    }
    [void]$stoppedServices.Add($Service)
    Invoke-Compose -RequiresEngine -ProjectName $projectName -Arguments @('stop', $Service) | Out-Null
}

function Start-TestDependency {
    param([Parameter(Mandatory)] [string] $Service, [switch] $NoWait)
    $arguments = @('up', '--no-deps', '--detach')
    if (-not $NoWait) { $arguments += @('--wait', '--wait-timeout', '90') }
    $arguments += $Service
    Invoke-Compose -RequiresEngine -ProjectName $projectName -Arguments $arguments | Out-Null
    [void]$stoppedServices.Remove($Service)
}

function Assert-Status {
    param([Parameter(Mandatory)] $Response, [Parameter(Mandatory)] [int] $Expected, [string] $Description)
    if ($Response.Status -ne $Expected) {
        throw "$Description returned HTTP $($Response.Status); expected $Expected."
    }
}

function Assert-DetectionPersisted {
    param(
        [Parameter(Mandatory)] $ExpectedIncident,
        [Parameter(Mandatory)] [string] $SourceName,
        [Parameter(Mandatory)] $PriorLastSuccess,
        [switch] $RequireUnchangedLastSuccess
    )
    $actualIncident = Get-Incident -Id ([string]$ExpectedIncident.id)
    if ($actualIncident.id -ne $ExpectedIncident.id -or $actualIncident.status -ne $ExpectedIncident.status) {
        throw 'The persisted incident ID or lifecycle status changed across the service restart.'
    }
    $detection = Wait-Until -Description 'persisted detection status' -Probe {
        $value = Get-DetectionStatus
        if ($null -ne $value) { return $value }
        return $null
    }
    $source = Get-Source -Detection $detection -Name $SourceName
    if ($null -eq $source -or $null -eq $source.lastSuccessAt) {
        throw "The persisted source timestamp for $SourceName is missing."
    }
    if ([DateTimeOffset]$source.lastSuccessAt -lt [DateTimeOffset]$PriorLastSuccess) {
        throw "The persisted source timestamp for $SourceName regressed."
    }
    if ($RequireUnchangedLastSuccess -and
        [DateTimeOffset]$source.lastSuccessAt -ne [DateTimeOffset]$PriorLastSuccess) {
        throw "The unavailable $SourceName source changed its last-success timestamp across Investigation restart."
    }
}

function Assert-PortAvailable {
    param([Parameter(Mandatory)] [int] $Port)
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) { throw "Required loopback test port $Port is already in use; no container was started." }
}

function Remove-DisposableProject {
    param([Parameter(Mandatory)] [string] $ProjectName)
    if ($ProjectName -notmatch '^traceforge-p7out-[0-9a-f]{10}$') {
        throw "Refusing cleanup for non-disposable Compose project '$ProjectName'."
    }

    $containerIds = @(& docker --context desktop-linux ps --all --quiet --filter "label=com.docker.compose.project=$ProjectName")
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect containers for the disposable Compose project.' }
    foreach ($containerId in $containerIds) {
        $containerProject = & docker --context desktop-linux inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' $containerId
        if ($LASTEXITCODE -ne 0 -or ($containerProject -join '').Trim() -ne $ProjectName) {
            throw "Refusing cleanup because container '$containerId' is not positively labeled for '$ProjectName'."
        }
        $containerService = & docker --context desktop-linux inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' $containerId
        if ($LASTEXITCODE -ne 0 -or ($containerService -join '').Trim() -notin $testServices) {
            throw "Refusing cleanup because container '$containerId' is not an expected service in '$ProjectName'."
        }
    }

    if ($containerIds.Count -gt 0) {
        $removeArguments = @('rm', '--stop', '--force') + $testServices
        Invoke-Compose -RequiresEngine -ProjectName $ProjectName -Arguments $removeArguments | Out-Null
    }

    $networkName = "${ProjectName}_default"
    $networkNames = @(& docker --context desktop-linux network ls --format '{{.Name}}')
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect Docker network names for the disposable Compose project.' }
    if ($networkNames -contains $networkName) {
        $labelOutput = & docker --context desktop-linux network inspect $networkName --format '{{ index .Labels "com.docker.compose.project" }}'
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect the disposable network '$networkName'." }
        if (($labelOutput -join '').Trim() -ne $ProjectName) {
            throw "Refusing to remove network '$networkName' because its Compose project label does not match."
        }
        $containerCountText = & docker --context desktop-linux network inspect $networkName --format '{{ len .Containers }}'
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect the scoped network '$networkName'." }
        if ([int](($containerCountText -join '').Trim()) -ne 0) {
            throw "Refusing to remove '$networkName' while it still has attached containers."
        }
        & docker --context desktop-linux network rm $networkName | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not remove the empty scoped network '$networkName'." }
    }

    foreach ($imageName in $builtImageNames.Values) {
        $image = "traceforge-phase7-outage-${imageName}:$ProjectName"
        $imageContainers = @(& docker --context desktop-linux ps --all --quiet --filter "ancestor=$image")
        if ($LASTEXITCODE -ne 0) { throw "Could not check containers using the disposable image '$image'." }
        if ($imageContainers.Count -gt 0) {
            throw "Refusing to remove disposable image '$image' while containers still use it."
        }
        $imageIds = @(& docker --context desktop-linux image ls --quiet $image)
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect the scoped disposable image '$image'." }
        if ($imageIds.Count -gt 0) {
            & docker --context desktop-linux image rm --no-prune $image | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not remove the scoped disposable image '$image'." }
        }
    }

    $projectVolumes = @(& docker --context desktop-linux volume ls --quiet --filter "label=com.docker.compose.project=$ProjectName")
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect disposable project volumes.' }
    $expectedVolume = "traceforge-phase7-outage-postgres-$ProjectName"
    foreach ($volumeName in $projectVolumes) {
        $volumeInfo = & docker --context desktop-linux volume inspect $volumeName --format '{{.Name}}|{{ index .Labels "com.docker.compose.project" }}|{{ index .Labels "com.docker.compose.volume" }}'
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect disposable volume '$volumeName'." }
        $parts = ($volumeInfo -join '').Trim().Split('|')
        if ($parts.Count -ne 3 -or $parts[0] -ne $expectedVolume -or
            $parts[1] -ne $ProjectName -or $parts[2] -ne 'phase7-postgres-data') {
            throw "Refusing cleanup of unexpected volume '$volumeName' in project '$ProjectName'."
        }
        $users = @(& docker --context desktop-linux ps --all --quiet --filter "volume=$volumeName")
        if ($LASTEXITCODE -ne 0) { throw "Could not check users of disposable volume '$volumeName'." }
        if ($users.Count -gt 0) { throw "Refusing to remove volume '$volumeName' while containers still use it." }
        & docker --context desktop-linux volume rm $volumeName | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not remove the exact disposable volume '$volumeName'." }
    }
}

function Assert-DisposableProjectUnused {
    param([Parameter(Mandatory)] [string] $ProjectName)
    if ($ProjectName -notmatch '^traceforge-p7out-[0-9a-f]{10}$') {
        throw "Refusing to use non-disposable Compose project '$ProjectName'."
    }
    $containers = @(& docker --context desktop-linux ps --all --quiet --filter "label=com.docker.compose.project=$ProjectName")
    if ($LASTEXITCODE -ne 0) { throw 'Could not check whether the generated Compose project already exists.' }
    if ($containers.Count -gt 0) { throw "Compose project '$ProjectName' already has containers; refusing to reuse it." }
    $networkName = "${ProjectName}_default"
    $networks = @(& docker --context desktop-linux network ls --format '{{.Name}}')
    if ($LASTEXITCODE -ne 0) { throw 'Could not check whether the generated Compose project network already exists.' }
    if ($networks -contains $networkName) { throw "Compose project '$ProjectName' already has a network; refusing to reuse it." }
    $expectedVolume = "traceforge-phase7-outage-postgres-$ProjectName"
    $volumes = @(& docker --context desktop-linux volume ls --quiet --filter "name=$expectedVolume")
    if ($LASTEXITCODE -ne 0) { throw 'Could not check whether the generated PostgreSQL volume already exists.' }
    if ($volumes.Count -gt 0) { throw "A volume matching '$expectedVolume' already exists; refusing to reuse this project name." }
    $projectVolumes = @(& docker --context desktop-linux volume ls --quiet --filter "label=com.docker.compose.project=$ProjectName")
    if ($LASTEXITCODE -ne 0) { throw 'Could not check existing volumes for the generated Compose project.' }
    if ($projectVolumes.Count -gt 0) { throw "Compose project '$ProjectName' already has labeled volumes; refusing to reuse it." }
}

Ensure-Manifest

$prepareProject = 'traceforge-phase7-outage'
$previousImageTag = $env:TRACEFORGE_OUTAGE_IMAGE_TAG
$validationProject = 'traceforge-p7out-0123456789'
try {
    $env:TRACEFORGE_OUTAGE_IMAGE_TAG = $prepareProject
    Invoke-Compose -ProjectName $prepareProject -Arguments @('config', '-q') | Out-Null
    $resolved = Get-ResolvedConfig -ProjectName $prepareProject
    Assert-ResolvedIsolation -ProjectName $prepareProject -Resolved $resolved

    $env:TRACEFORGE_OUTAGE_IMAGE_TAG = $validationProject
    Invoke-Compose -ProjectName $validationProject -Arguments @('config', '-q') | Out-Null
    $runResolved = Get-ResolvedConfig -ProjectName $validationProject
    Assert-ResolvedIsolation -ProjectName $validationProject -Resolved $runResolved
    Assert-RunImageNames -Resolved $runResolved -ProjectName $validationProject
} finally {
    if ($null -eq $previousImageTag) {
        Remove-Item Env:TRACEFORGE_OUTAGE_IMAGE_TAG -ErrorAction SilentlyContinue
    } else {
        $env:TRACEFORGE_OUTAGE_IMAGE_TAG = $previousImageTag
    }
}
Write-Host "Compose configuration validated: $manifestPath"
Write-Host 'Isolation verified for both default and run-tagged configurations: project-generated network, one uniquely named PostgreSQL test volume, tmpfs Tempo, and only loopback ports 18080/18090.'

if ($PrepareOnly) {
    Write-Host 'PrepareOnly set; no containers were started, stopped, or removed.'
    return
}
if (-not [string]::IsNullOrWhiteSpace($CleanupProject)) {
    $cleanupImageTag = $env:TRACEFORGE_OUTAGE_IMAGE_TAG
    try {
        $env:TRACEFORGE_OUTAGE_IMAGE_TAG = $CleanupProject
        Remove-DisposableProject -ProjectName $CleanupProject
    } finally {
        if ($null -eq $cleanupImageTag) {
            Remove-Item Env:TRACEFORGE_OUTAGE_IMAGE_TAG -ErrorAction SilentlyContinue
        } else {
            $env:TRACEFORGE_OUTAGE_IMAGE_TAG = $cleanupImageTag
        }
    }
    Write-Host "Removed only project-labeled containers, generated network, unique build images, and disposable PostgreSQL volume for $CleanupProject; application volumes were not touched."
    return
}
if (-not $RunOutages) {
    Write-Host 'No outage experiment was requested. Pass -RunOutages only when ready to run the disposable matrix.'
    return
}

Assert-PortAvailable -Port 18080
Assert-PortAvailable -Port 18090
$projectName = 'traceforge-p7out-' + [guid]::NewGuid().ToString('N').Substring(0, 10)
Assert-DisposableProjectUnused -ProjectName $projectName
$stoppedServices = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$cleanupErrors = [System.Collections.Generic.List[string]]::new()
$projectTouched = $false
Write-Host "Disposable Compose project: $projectName"
Write-Host "If interrupted, clean only this project with: .\scripts\verify-phase7-outages.ps1 -CleanupProject $projectName"

try {
    $originalImageTag = $env:TRACEFORGE_OUTAGE_IMAGE_TAG
    $env:TRACEFORGE_OUTAGE_IMAGE_TAG = $projectName
    $runResolved = Get-ResolvedConfig -ProjectName $projectName
    Assert-ResolvedIsolation -ProjectName $projectName -Resolved $runResolved
    Assert-RunImageNames -Resolved $runResolved -ProjectName $projectName
    $projectTouched = $true
    Invoke-Compose -RequiresEngine -ProjectName $projectName -Arguments @(
        'up', '--build', '--detach', '--wait', '--wait-timeout', '300'
    ) | Out-Null
    Invoke-Compose -RequiresEngine -ProjectName $projectName -Arguments @('ps') | ForEach-Object { Write-Host $_ }

    $baseline = Wait-Until -Description 'a clean healthy detector baseline' -TimeoutSeconds 120 -Probe {
        $detection = Get-DetectionStatus
        if ($null -eq $detection -or $detection.status -ne 'CURRENT' -or $null -eq $detection.latestCycle) { return $null }
        if (@($detection.services | Where-Object { $_.status -ne 'UP' -or $_.freshnessStatus -ne 'CURRENT' }).Count -gt 0) { return $null }
        $open = Get-IncidentPage -Status OPEN
        if (@($open.items).Count -gt 0) { return $null }
        return $detection
    }
    $baselineCycleId = [string]$baseline.latestCycle.cycleId
    Write-Host "PASS baseline: cycle $baselineCycleId is current, all four probed services are UP, and no incidents are open."

    # SERVICE_NOT_READY: inventory readiness goes down and returns.
    $inventoryBaselineCycleId = [string](Get-DetectionStatus).latestCycle.cycleId
    Stop-TestDependency -Service 'inventory-service'
    $firstInventoryFailure = Wait-Until -Description 'first completed failed Inventory probe without an incident' -TimeoutSeconds 45 -Probe {
        $detection = Get-DetectionStatus
        if ($null -eq $detection -or $null -eq $detection.latestCycle -or
            $detection.latestCycle.cycleId -eq $inventoryBaselineCycleId) { return $null }
        $health = Get-ServiceSnapshot -Detection $detection -Name 'inventory-service'
        if ($null -eq $health -or $health.status -ne 'DOWN' -or
            $health.freshnessStatus -ne 'CURRENT') { return $null }
        return [pscustomobject]@{ Detection = $detection; Health = $health }
    }
    if ($firstInventoryFailure.Health.incidentOpen) {
        throw 'Inventory incident opened on the first failed probe instead of waiting for a second consecutive failure.'
    }
    $firstInventoryFailureCycleId = [string]$firstInventoryFailure.Detection.latestCycle.cycleId
    Write-Host "Observed first failed Inventory probe in cycle $firstInventoryFailureCycleId with no incident open."
    $secondInventoryFailure = Wait-Until -Description 'second consecutive failed Inventory probe opening the incident' -TimeoutSeconds 45 -Probe {
        $detection = Get-DetectionStatus
        if ($null -eq $detection -or $null -eq $detection.latestCycle -or
            $detection.latestCycle.cycleId -eq $firstInventoryFailureCycleId) { return $null }
        $health = Get-ServiceSnapshot -Detection $detection -Name 'inventory-service'
        if ($null -eq $health -or $health.status -ne 'DOWN' -or
            $health.freshnessStatus -ne 'CURRENT' -or -not $health.incidentOpen) { return $null }
        $incident = Find-Incident -Status OPEN -RuleKey 'SERVICE_NOT_READY' -SourceReference 'inventory-service'
        if ($null -eq $incident) { return $null }
        return [pscustomobject]@{ Detection = $detection; Health = $health; Incident = $incident }
    }
    $inventoryIncident = $secondInventoryFailure.Incident
    if (@(Get-MatchingIncidents -Status OPEN -RuleKey 'SERVICE_NOT_READY' -SourceReference 'inventory-service').Count -ne 1) {
        throw 'Repeated inventory failure observations created duplicate open incident episodes.'
    }
    $inventoryDetection = $secondInventoryFailure.Detection
    $inventoryHealth = $secondInventoryFailure.Health
    if ($inventoryHealth.status -ne 'DOWN' -or $inventoryHealth.freshnessStatus -ne 'CURRENT' -or -not $inventoryHealth.incidentOpen) {
        throw 'Inventory outage health state or current observation freshness did not match the contract.'
    }
    Write-Host "Observed second failed Inventory probe in cycle $($inventoryDetection.latestCycle.cycleId); one open incident $($inventoryIncident.id) exists."
    Start-TestDependency -Service 'inventory-service' -NoWait
    $firstInventoryRecovery = Wait-Until -Description 'first fresh UP Inventory probe while the same incident remains open' -TimeoutSeconds 60 -Probe {
        $detection = Get-DetectionStatus
        if ($null -eq $detection -or $null -eq $detection.latestCycle -or
            $detection.latestCycle.cycleId -eq [string]$inventoryDetection.latestCycle.cycleId) { return $null }
        $health = Get-ServiceSnapshot -Detection $detection -Name 'inventory-service'
        if ($null -eq $health -or $health.status -ne 'UP' -or
            $health.freshnessStatus -ne 'CURRENT') { return $null }
        return [pscustomobject]@{ Detection = $detection; Health = $health }
    }
    if (-not $firstInventoryRecovery.Health.incidentOpen) {
        throw 'Inventory incident resolved on the first UP probe instead of waiting for a second consecutive UP observation.'
    }
    $firstInventoryRecoveryCycleId = [string]$firstInventoryRecovery.Detection.latestCycle.cycleId
    Write-Host "Observed first UP Inventory probe in cycle $firstInventoryRecoveryCycleId; incident $($inventoryIncident.id) remains open."
    $resolvedInventory = Wait-Until -Description 'second consecutive UP Inventory probe resolving the original incident' -TimeoutSeconds 45 -Probe {
        $detection = Get-DetectionStatus
        if ($null -eq $detection -or $null -eq $detection.latestCycle -or
            $detection.latestCycle.cycleId -eq $firstInventoryRecoveryCycleId) { return $null }
        $health = Get-ServiceSnapshot -Detection $detection -Name 'inventory-service'
        if ($null -eq $health -or $health.status -ne 'UP' -or
            $health.freshnessStatus -ne 'CURRENT' -or $health.incidentOpen) { return $null }
        $incident = Find-Incident -Status RESOLVED -RuleKey 'SERVICE_NOT_READY' -SourceReference 'inventory-service'
        if ($null -eq $incident) { return $null }
        return [pscustomobject]@{ Detection = $detection; Incident = $incident }
    }
    $resolvedInventoryIncident = $resolvedInventory.Incident
    if ($resolvedInventoryIncident.id -ne $inventoryIncident.id) { throw 'Inventory recovery did not resolve the original incident episode.' }
    if (@(Get-MatchingIncidents -Status RESOLVED -RuleKey 'SERVICE_NOT_READY' -SourceReference 'inventory-service').Count -ne 1) {
        throw 'Inventory recovery produced more than one resolved episode for the same service outage.'
    }
    Write-Host "Observed second UP Inventory probe in cycle $($resolvedInventory.Detection.latestCycle.cycleId); incident $($inventoryIncident.id) resolved."
    Write-Host "PASS SERVICE_NOT_READY: incident $($inventoryIncident.id) opened after two failed probes and resolved after two UP probes."

    # ORDER_RECOVERY_STALLED plus an unavailable required Order signal.
    $orderKey = 'tf-p7out-' + [guid]::NewGuid().ToString('N')
    $orderBody = @{ sku = 'SKU-ALPHA'; quantity = 1 } | ConvertTo-Json -Compress
    $pendingOrderResponse = Invoke-Api -Method POST -Path '/api/v1/orders' `
        -Headers @{ 'Idempotency-Key' = $orderKey; 'X-TraceForge-Failure' = 'payment-decline-compensation-unavailable' } `
        -Body $orderBody
    Assert-Status -Response $pendingOrderResponse -Expected 503 -Description 'Controlled incomplete-compensation order'
    if ($pendingOrderResponse.Body.status -ne 'COMPENSATION_REQUIRED' -or $pendingOrderResponse.Body.inventoryReleased) {
        throw 'The isolated failure path did not leave compensation explicitly pending.'
    }
    $orderId = [string]$pendingOrderResponse.Body.id
    $orderIncident = Wait-ForIncident -Status OPEN -RuleKey 'ORDER_RECOVERY_STALLED' -SourceReference $orderId -TimeoutSeconds 45
    $orderDetectionBeforeOutage = Get-DetectionStatus
    $orderSourceBeforeOutage = Get-Source -Detection $orderDetectionBeforeOutage -Name 'order-attention'
    if ($null -eq $orderSourceBeforeOutage -or $null -eq $orderSourceBeforeOutage.lastSuccessAt) {
        throw 'Order source has no successful baseline timestamp before the outage.'
    }
    $orderLastSuccessBeforeOutage = [DateTimeOffset]$orderSourceBeforeOutage.lastSuccessAt
    Stop-TestDependency -Service 'order-service'
    $staleOrderDetection = Wait-Until -Description 'the Order source to become stale after its last success' -TimeoutSeconds 55 -Probe {
        $detection = Get-DetectionStatus
        if ($null -eq $detection) { return $null }
        $source = Get-Source -Detection $detection -Name 'order-attention'
        if ($null -eq $source -or $source.status -ne 'STALE' -or $source.errorCode -ne 'UPSTREAM_UNAVAILABLE') { return $null }
        return $detection
    }
    $staleOrderSource = Get-Source -Detection $staleOrderDetection -Name 'order-attention'
    if ([DateTimeOffset]$staleOrderSource.lastSuccessAt -ne $orderLastSuccessBeforeOutage) {
        throw 'Failed Order reads changed the persisted last successful observation timestamp.'
    }
    $stillOpenOrder = Find-Incident -Status OPEN -RuleKey 'ORDER_RECOVERY_STALLED' -SourceReference $orderId
    if ($null -eq $stillOpenOrder -or $stillOpenOrder.id -ne $orderIncident.id) {
        throw 'An unavailable or stale Order source resolved or duplicated the recovery incident.'
    }
    if (@(Get-MatchingIncidents -Status OPEN -RuleKey 'ORDER_RECOVERY_STALLED' -SourceReference $orderId).Count -ne 1) {
        throw 'Stale Order observations created duplicate open recovery incident episodes.'
    }

    # Investigation remains available while its required Order source is down.
    # Restarting it during this outage proves the source's last-success value
    # and open incident survive without allowing a new successful observation.
    $openOrderIncidentBeforeRestart = Get-Incident -Id ([string]$orderIncident.id)
    $staleCycleId = [string]$staleOrderDetection.latestCycle.cycleId
    Stop-TestDependency -Service 'investigation-service'
    Assert-Status -Response (Invoke-Api -Method GET -Path '/api/v1/health') -Expected 200 -Description 'Gateway health while Investigation is unavailable'
    Assert-Status -Response (Invoke-Api -Method GET -Path '/api/v1/detection-status') -Expected 503 -Description 'Detection proxy while Investigation is unavailable'
    Assert-Status -Response (Invoke-Api -Method GET -Path '/api/v1/incidents?status=OPEN&limit=100') -Expected 503 -Description 'Incident proxy while Investigation is unavailable'
    Start-TestDependency -Service 'investigation-service'
    [void](Wait-Until -Description 'Investigation readiness after restart' -TimeoutSeconds 60 -Probe {
        $response = Invoke-WebRequest -Uri "$investigationBase/readyz" -SkipHttpErrorCheck -TimeoutSec 5
        if ([int]$response.StatusCode -eq 200) { return $true }
        return $null
    })
    $restartedOrderDetection = Wait-ForCycleAfter -CycleId $staleCycleId -TimeoutSeconds 30
    $restartedOrderSource = Get-Source -Detection $restartedOrderDetection -Name 'order-attention'
    if ($null -eq $restartedOrderSource -or $restartedOrderSource.status -ne 'STALE' -or
        $restartedOrderSource.errorCode -ne 'UPSTREAM_UNAVAILABLE') {
        throw 'Investigation restart did not retain the stale Order source state while Order remained unavailable.'
    }
    Assert-DetectionPersisted -ExpectedIncident $openOrderIncidentBeforeRestart `
        -SourceName 'order-attention' -PriorLastSuccess $orderLastSuccessBeforeOutage -RequireUnchangedLastSuccess
    $stillOpenAfterInvestigationRestart = Find-Incident -Status OPEN -RuleKey 'ORDER_RECOVERY_STALLED' -SourceReference $orderId
    if ($null -eq $stillOpenAfterInvestigationRestart -or $stillOpenAfterInvestigationRestart.id -ne $orderIncident.id) {
        throw 'Investigation restart lost or duplicated the open recovery incident.'
    }
    Write-Host 'PASS Investigation restart: Gateway health stayed available, incident proxies returned 503 during downtime, and stale Order freshness plus the open incident persisted.'

    Start-TestDependency -Service 'order-service'
    $recoveredOrder = Wait-Until -Description 'the saga to finish explicit compensation after Order returns' -TimeoutSeconds 90 -Probe {
        $response = Invoke-Api -Method GET -Path "/api/v1/orders/$orderId"
        if ($response.Status -ne 200 -or $response.Body.status -ne 'FAILED' -or -not $response.Body.inventoryReleased) { return $null }
        return $response.Body
    }
    $resolvedOrderIncident = Wait-ForIncident -Status RESOLVED -RuleKey 'ORDER_RECOVERY_STALLED' -SourceReference $orderId -TimeoutSeconds 45
    if ($resolvedOrderIncident.id -ne $orderIncident.id) { throw 'Explicit terminal compensation did not resolve the original Order incident.' }
    if (@(Get-MatchingIncidents -Status RESOLVED -RuleKey 'ORDER_RECOVERY_STALLED' -SourceReference $orderId).Count -ne 1) {
        throw 'Terminal compensation produced more than one resolved Order incident episode.'
    }
    $orderIncidentRecord = Get-Incident -Id ([string]$orderIncident.id)
    Write-Host "PASS Order outage: stale source retained incident $($orderIncident.id); explicit compensation resolved that episode after restart."

    # Database container outage: only the project-scoped disposable test database is stopped.
    $preDatabaseDetection = Get-DetectionStatus
    $preDatabaseSource = Get-Source -Detection $preDatabaseDetection -Name 'order-attention'
    $preDatabaseLastSuccess = [DateTimeOffset]$preDatabaseSource.lastSuccessAt
    $databaseIncident = Get-Incident -Id ([string]$orderIncident.id)
    Stop-TestDependency -Service 'postgres'
    $databaseReadiness = Invoke-WebRequest -Uri "$investigationBase/readyz" -SkipHttpErrorCheck -TimeoutSec 10
    Assert-Status -Response ([pscustomobject]@{ Status = [int]$databaseReadiness.StatusCode }) -Expected 503 -Description 'Investigation readiness while PostgreSQL is unavailable'
    $databaseLiveness = Invoke-WebRequest -Uri "$investigationBase/healthz" -SkipHttpErrorCheck -TimeoutSec 10
    Assert-Status -Response ([pscustomobject]@{ Status = [int]$databaseLiveness.StatusCode }) -Expected 200 -Description 'Investigation liveness while PostgreSQL is unavailable'
    $databaseApiResponse = Invoke-Api -Method GET -Path '/api/v1/detection-status'
    Assert-Status -Response $databaseApiResponse -Expected 503 -Description 'Detection API while PostgreSQL is unavailable'
    if ($databaseApiResponse.Text -notmatch 'DETECTION_STORE_UNAVAILABLE') {
        throw 'Database outage response did not expose the safe detection-store error code.'
    }
    Start-TestDependency -Service 'postgres'
    $databaseReadyAgain = Wait-Until -Description 'Investigation readiness after PostgreSQL restart' -TimeoutSeconds 60 -Probe {
        $response = Invoke-WebRequest -Uri "$investigationBase/readyz" -SkipHttpErrorCheck -TimeoutSec 5
        if ([int]$response.StatusCode -eq 200) { return $true }
        return $null
    }
    Assert-DetectionPersisted -ExpectedIncident $databaseIncident -SourceName 'order-attention' -PriorLastSuccess $preDatabaseLastSuccess
    Write-Host 'PASS PostgreSQL outage: readiness/API failures were explicit and incident/freshness data in the project-scoped test volume survived container stop/start.'

    # Optional trace retrieval outage does not disable deterministic detection or alter incident lifecycle.
    $incidentTraceId = [string]$orderIncidentRecord.originTraceId
    if ($incidentTraceId -notmatch '^[0-9a-f]{32}$') {
        $incidentTrace = @($orderIncidentRecord.evidence | Where-Object { $_.traceId } | Select-Object -First 1)
        if ($incidentTrace.Count -gt 0) { $incidentTraceId = [string]$incidentTrace[0].traceId }
    }
    if ($incidentTraceId -notmatch '^[0-9a-f]{32}$') { throw 'The isolated recovery incident did not retain a valid trace reference.' }
    $traceAvailable = Wait-Until -Description 'the incident trace to be queryable before Tempo outage' -TimeoutSeconds 45 -Probe {
        $response = Invoke-Api -Method GET -Path "/api/v1/traces/$incidentTraceId"
        if ($response.Status -eq 200 -and $response.Body.traceId -eq $incidentTraceId) { return $response }
        return $null
    }
    $incidentBeforeTraceOutage = Get-Incident -Id ([string]$orderIncident.id)
    $traceBaselineCycle = (Get-DetectionStatus).latestCycle.cycleId
    Stop-TestDependency -Service 'tempo'
    Assert-Status -Response (Invoke-Api -Method GET -Path "/api/v1/traces/$incidentTraceId") -Expected 503 -Description 'Trace query while Tempo is unavailable'
    $partialInvestigation = Invoke-Api -Method POST -Path "/api/v1/incidents/$($orderIncident.id)/investigations"
    Assert-Status -Response $partialInvestigation -Expected 200 -Description 'Investigation with optional Tempo unavailable'
    if ($partialInvestigation.Body.status -ne 'PARTIAL' -or
        @($partialInvestigation.Body.evidenceGaps | Where-Object { $_.code -eq 'TRACE_SOURCE_UNAVAILABLE' }).Count -eq 0) {
        throw 'Tempo outage was not represented as a partial report with an explicit trace evidence gap.'
    }
    $traceOutageCycle = Wait-ForCycleAfter -CycleId ([string]$traceBaselineCycle) -TimeoutSeconds 30
    if ($traceOutageCycle.latestCycle.status -ne 'COMPLETE') {
        throw 'Deterministic detection did not complete while optional Tempo evidence was unavailable.'
    }
    $incidentAfterTraceOutage = Get-Incident -Id ([string]$orderIncident.id)
    if ($incidentAfterTraceOutage.status -ne $incidentBeforeTraceOutage.status -or
        $incidentAfterTraceOutage.occurrenceCount -ne $incidentBeforeTraceOutage.occurrenceCount) {
        throw 'An optional trace backend outage changed incident lifecycle or occurrence count.'
    }
    Start-TestDependency -Service 'tempo'
    # Tempo's backing store is intentionally tmpfs, so the pre-outage trace
    # need not survive a container stop. Prove recovery with a new correlated
    # business trace after Tempo is healthy again.
    $traceId = [guid]::NewGuid().ToString('N').ToLowerInvariant()
    $parentSpanId = [guid]::NewGuid().ToString('N').Substring(0, 16).ToLowerInvariant()
    $recoveryOrderKey = 'tf-p7out-' + [guid]::NewGuid().ToString('N')
    $recoveryOrderResponse = Invoke-Api -Method POST -Path '/api/v1/orders' `
        -Headers @{
            'Idempotency-Key' = $recoveryOrderKey
            traceparent = "00-$traceId-$parentSpanId-01"
        } `
        -Body $orderBody
    Assert-Status -Response $recoveryOrderResponse -Expected 201 -Description 'Successful order after Tempo restart'
    if ($recoveryOrderResponse.Body.status -ne 'CONFIRMED') {
        throw 'The post-restart healthy order did not reach CONFIRMED.'
    }
    $traceRestored = Wait-Until -Description 'a new successful order trace to be queryable after Tempo restart' -TimeoutSeconds 45 -Probe {
        $response = Invoke-Api -Method GET -Path "/api/v1/traces/$traceId"
        if ($response.Status -ne 200 -or $response.Body.traceId -ne $traceId) { return $null }
        $services = @($response.Body.spans | ForEach-Object { $_.service } | Select-Object -Unique)
        $expectedServices = @('api-gateway', 'order-service', 'inventory-service', 'payment-service')
        if (Compare-Object -ReferenceObject $expectedServices -DifferenceObject $services) { return $null }
        return $response
    }
    if ($null -eq $traceRestored) { throw 'The post-restart order trace was not queryable from all expected services.' }
    $traceId = [string]$traceRestored.Body.traceId
    Write-Host 'PASS Tempo outage: report exposed an optional trace gap, detection completed with incident state unchanged, and a new correlated order trace was queryable after restart.'

    # Collector is not a detector input; keep Tempo available while its exporter is stopped.
    $collectorBaseline = Get-DetectionStatus
    $collectorIncidentBefore = Get-Incident -Id ([string]$orderIncident.id)
    Stop-TestDependency -Service 'otel-collector'
    $collectorCycle = Wait-ForCycleAfter -CycleId ([string]$collectorBaseline.latestCycle.cycleId) -TimeoutSeconds 30
    if ($collectorCycle.latestCycle.status -ne 'COMPLETE') {
        throw 'Deterministic detection did not complete while the optional Collector was unavailable.'
    }
    Assert-Status -Response (Invoke-Api -Method GET -Path "/api/v1/traces/$traceId") -Expected 200 -Description 'Stored Tempo trace while Collector is unavailable'
    $collectorIncidentAfter = Get-Incident -Id ([string]$orderIncident.id)
    if ($collectorIncidentAfter.status -ne $collectorIncidentBefore.status -or
        $collectorIncidentAfter.occurrenceCount -ne $collectorIncidentBefore.occurrenceCount) {
        throw 'Collector outage changed incident lifecycle or occurrence count.'
    }
    Start-TestDependency -Service 'otel-collector'
    Write-Host 'PASS Collector outage: detection completed and stored Tempo evidence remained queryable.'
    Write-Host 'All scoped Phase 7 container-outage experiments passed.'
}
finally {
    foreach ($service in $mutableDependencies) {
        if ($stoppedServices.Contains($service)) {
            try {
                Start-TestDependency -Service $service
            } catch {
                $cleanupErrors.Add("Could not restore disposable service '$service': $($_.Exception.Message)")
            }
        }
    }
    if ($projectTouched) {
        try {
            Remove-DisposableProject -ProjectName $projectName
        } catch {
            $cleanupErrors.Add("Disposable project cleanup failed: $($_.Exception.Message)")
        }
    }
    if ($null -eq $originalImageTag) {
        Remove-Item Env:TRACEFORGE_OUTAGE_IMAGE_TAG -ErrorAction SilentlyContinue
    } else {
        $env:TRACEFORGE_OUTAGE_IMAGE_TAG = $originalImageTag
    }
    if ($cleanupErrors.Count -gt 0) {
        throw ($cleanupErrors -join ' ')
    }
}
