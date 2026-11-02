param(
    [string]$BuildDirectory='C:\fpga_build\tcb705_parallel_fp32_20261024',
    [ValidateSet('csim','synthesis','cosim','package','all')][string]$Stage='all',
    [ValidateSet('controller','controller_throughput','contract')][string]$Profile='controller_throughput'
)
$ErrorActionPreference='Stop'
$env:PROCESSOR_ARCHITECTURE='AMD64'
$root=Split-Path -Parent $PSScriptRoot
$source=Join-Path $root 'hls_source\tcb705_parallel_fp32'
$BuildDirectory=[IO.Path]::GetFullPath($BuildDirectory)
if($BuildDirectory -match '[^\x00-\x7F]') {
    throw 'Use an ASCII-only build directory for Windows Vitis HLS.'
}
if($BuildDirectory.TrimEnd('\') -eq $root.TrimEnd('\') -or
   $BuildDirectory.StartsWith((Join-Path $root 'hls_source')+'\',[StringComparison]::OrdinalIgnoreCase)) {
    throw 'BuildDirectory must not overwrite the project or its source tree.'
}
$src=Join-Path $BuildDirectory 'src'
$reference=Join-Path $BuildDirectory 'tcb705'
$nativeReference=Join-Path $BuildDirectory 'reference\tcb_planner'
$work=Join-Path $BuildDirectory "hls_$Profile"
$logs=Join-Path $BuildDirectory "logs_$Profile"
$cfg=switch($Profile) {
    'controller' {'parallel_controller_100mhz.cfg'}
    'controller_throughput' {'controller_throughput.cfg'}
    'contract' {'parallel_srs_contract.cfg'}
}
$run='D:\Xilinx\Vitis\2024.2\bin\vitis-run.bat'
$compile='D:\Xilinx\Vitis\2024.2\bin\v++.bat'
foreach($required in @($source,$run,$compile,(Join-Path $source $cfg))) {
    if(!(Test-Path -LiteralPath $required)){throw "Required input/tool is missing: $required"}
}
foreach($directory in @($src,$reference,$nativeReference,$logs)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}
# Retain all relative includes and nested test files. In tests/, the existing
# ../../tcb705 reference resolves to the old, read-only solver copied below.
foreach($item in Get-ChildItem -LiteralPath $source -Force) {
    Copy-Item -LiteralPath $item.FullName -Destination $src -Recurse -Force
}
foreach($item in Get-ChildItem -LiteralPath (Join-Path $root 'hls_source\tcb705') -File) {
    Copy-Item -LiteralPath $item.FullName -Destination $reference -Force
}
Copy-Item -LiteralPath (Join-Path $root 'native\tcb_planner\math7.hpp') -Destination $nativeReference -Force
Copy-Item -LiteralPath (Join-Path $root 'hls_source\tcb705\vectors.txt') -Destination (Join-Path $src 'vectors.txt') -Force

# Reject stale RTL if a later standalone cosim/package call changed any design
# input. Tests can change independently; each test profile has a separate RTL
# work directory and a separate successful-synthesis receipt.
$designInputs=@(Get-ChildItem -LiteralPath $src -File | Where-Object {
    $_.Extension -in @('.cpp','.h','.hpp') -or $_.Name -eq $cfg
} | Sort-Object Name | ForEach-Object {
    [ordered]@{name=$_.Name;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
$fingerprint=ConvertTo-Json -InputObject $designInputs -Depth 4 -Compress
$receipt=Join-Path $logs 'synthesis_inputs.json'
Push-Location $src
try {
    foreach($step in @('csim','synthesis','cosim','package')) {
        if($Stage -ne 'all' -and $Stage -ne $step){continue}
        if($step -in @('cosim','package')) {
            if(!(Test-Path -LiteralPath $receipt) -or
               (Get-Content -LiteralPath $receipt -Raw).Trim() -ne $fingerprint) {
                throw "No matching successful synthesis for $Profile. Run -Stage synthesis first."
            }
        }
        $log=Join-Path $logs "$step.log"
        if($step -eq 'synthesis') {
            Write-Output "COMMAND: $compile -c --mode hls --config $cfg --work_dir $work"
            & $compile -c --mode hls --config $cfg --work_dir $work *> $log
        }else{
            Write-Output "COMMAND: $run --mode hls --$step --config $cfg --work_dir $work"
            & $run --mode hls "--$step" --config $cfg --work_dir $work *> $log
        }
        if($LASTEXITCODE -ne 0){throw "$Profile $step failed; inspect $log"}
        if($step -eq 'synthesis') {
            Set-Content -LiteralPath $receipt -Value $fingerprint -Encoding ascii
        }
        if($step -eq 'cosim') {
            $content=Get-Content -LiteralPath $log -Raw
            if($content -notmatch 'C/RTL co-simulation finished: PASS') {
                throw "Cosim did not confirm PASS; inspect $log"
            }
        }
        Write-Output "PARALLEL_HLS_$($step.ToUpperInvariant()) COMPLETE [$Profile]: $log"
    }
}finally{Pop-Location}
Write-Output "Reports: $work\hls\syn\report and $work\hls\sim\report"
Write-Output '10 ns is a requested HLS clock. Only post-route timing and valid-result throughput measurements establish acceptance.'
