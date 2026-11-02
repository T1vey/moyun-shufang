#Requires -Version 5.1
param(
    [string]$Python='python',
    [switch]$PlannerOnly,
    [switch]$AppOnly,
    [switch]$RequireNative
)
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
if ($PlannerOnly -and $AppOnly) {throw 'Choose at most one subset'}
$env:R1A_UPSTREAM_DIR=Join-Path $taskRoot 'vendor\e1pco'
foreach ($taskNative in @(@('SO101_IK_DLL','ik_step.dll'),@('SO101_TARGET_DLL','ik_target.dll'))) {
    $taskPath=Join-Path $taskRoot ('build\target_ik\host\'+$taskNative[1])
    if (Test-Path -LiteralPath $taskPath) {
        [Environment]::SetEnvironmentVariable($taskNative[0],$taskPath,'Process')
    } elseif ($RequireNative) {throw "Missing native numerical gate: $taskPath"}
}
$taskFailures=0
if (-not $AppOnly) {
    Push-Location (Join-Path $taskRoot 'planner_source')
    try {
        & $Python -B -m unittest discover -s tests
        if ($LASTEXITCODE -ne 0) {$taskFailures++}
    } finally {Pop-Location}
}
if (-not $PlannerOnly) {
    Push-Location $taskRoot
    try {
        & $Python -B -m unittest discover -s tests
        if ($LASTEXITCODE -ne 0) {$taskFailures++}
    } finally {Pop-Location}
}
exit $taskFailures
