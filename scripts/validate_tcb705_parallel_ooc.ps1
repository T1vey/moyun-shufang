param(
    [Parameter(Mandatory=$true)][string]$SynthesisRoot,
    [Parameter(Mandatory=$true)][string]$OutDirectory
)
$ErrorActionPreference='Stop'
$env:PROCESSOR_ARCHITECTURE='AMD64'
$projectRoot=Split-Path -Parent $PSScriptRoot
$sourceRtl=Join-Path ([IO.Path]::GetFullPath($SynthesisRoot)) 'hls\syn\verilog'
$OutDirectory=[IO.Path]::GetFullPath($OutDirectory)
$script=Join-Path $projectRoot 'hw\parallel\validate_ooc.tcl'
$vivado='D:\Xilinx\Vivado\2024.2\bin\vivado.bat'
if($OutDirectory -match '[^\x00-\x7F]') {throw 'Use an ASCII-only OutDirectory.'}
if(!(Test-Path -LiteralPath (Join-Path $sourceRtl 'tcb_planner_parallel.v'))) {
    throw "HLS synthesized top is missing: $sourceRtl\tcb_planner_parallel.v"
}
foreach($required in @($script,$vivado)) {
    if(!(Test-Path -LiteralPath $required)){throw "Missing input/tool: $required"}
}
if(Test-Path -LiteralPath $OutDirectory) {
    if(@(Get-ChildItem -LiteralPath $OutDirectory -Force).Count) {
        throw 'OutDirectory must be new or empty; existing implementation results are preserved.'
    }
}
$rtl=Join-Path $OutDirectory 'rtl'
New-Item -ItemType Directory -Force -Path $rtl | Out-Null
# Copy the generated RTL, ROM data and floating-point-IP Tcl scripts into this
# isolated experiment. No project, IP repository or board file is overwritten.
foreach($item in Get-ChildItem -LiteralPath $sourceRtl -File) {
    Copy-Item -LiteralPath $item.FullName -Destination $rtl -Force
}
if(!@(Get-ChildItem -LiteralPath $rtl -Filter '*_ip.tcl' -File).Count) {
    throw 'Floating-point IP generation scripts are missing; a black-box-only synthesis is not valid.'
}
$files=@(Get-ChildItem -LiteralPath $rtl -File | Sort-Object Name | ForEach-Object {
    [ordered]@{name=$_.Name;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
$manifest=[ordered]@{
    schema='tcb705-parallel-ooc-inputs-v1'
    source_rtl=$sourceRtl
    top='tcb_planner_parallel'
    part='xc7z020clg400-2'
    requested_period_ns=10.0
    requested_uncertainty_ns=0.3
    files=$files
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutDirectory 'inputs.json') -Encoding utf8
Write-Output "COMMAND: $vivado -mode batch -source $script -tclargs $rtl $OutDirectory"
Push-Location $OutDirectory
try {
    & $vivado -mode batch -source $script -log (Join-Path $OutDirectory 'vivado.log') `
        -journal (Join-Path $OutDirectory 'vivado.jou') -tclargs $rtl $OutDirectory `
        *> (Join-Path $OutDirectory 'console.log')
    if($LASTEXITCODE -ne 0){throw "OOC validation failed; inspect $OutDirectory\console.log and reports."}
}finally{Pop-Location}
$receipt=Join-Path $OutDirectory 'ooc_result.json'
if(!(Test-Path -LiteralPath $receipt)){throw 'Vivado returned without a validation result.'}
$result=Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
if($result.status -ne 'PASS' -or $result.setup_slack_ns -lt 0 -or
   $result.hold_slack_ns -lt 0 -or $result.black_boxes -ne 0 -or $result.drc_errors -ne 0) {
    throw "OOC result did not pass: $receipt"
}
$timing=Join-Path $OutDirectory 'timing_routed.rpt'
if(!(Test-Path -LiteralPath $timing)){throw 'Routed timing summary is missing.'}
Write-Output (Get-Content -LiteralPath $timing | Select-String -Pattern 'WNS\(ns\)' -Context 0,2 | Select-Object -First 1 | Out-String)
Write-Output "OOC internal timing PASS: setup $($result.setup_slack_ns) ns; hold $($result.hold_slack_ns) ns."
Write-Output 'This validates the standalone core only. No full-system bitstream was built or programmed; AXI boundary integration is not verified.'
