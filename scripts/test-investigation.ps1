$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$testExitCode = 1
$cleanupExitCode = 0
Push-Location $repoRoot
try {
    $project = 'traceforge-investigation-tests'
    $arguments = @(
        'compose', '--project-name', $project, '--profile', 'test',
        'run', '--build', '--rm', 'investigation-test', 'pytest', '-q', '-s'
    )
    & docker @arguments
    $testExitCode = $LASTEXITCODE
} finally {
    # This service has only a tmpfs data directory and a unique Compose project name.
    & docker compose --project-name traceforge-investigation-tests --profile test rm --stop --force incident-test-postgres *> $null
    $cleanupExitCode = $LASTEXITCODE
    Pop-Location
}

if ($testExitCode -ne 0) {
    exit $testExitCode
}
if ($cleanupExitCode -ne 0) {
    Write-Error 'The isolated Investigation test database container could not be removed.'
    exit $cleanupExitCode
}
exit 0
