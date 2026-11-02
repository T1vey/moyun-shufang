param([string]$BuildDirectory='C:\fpga_build\tcb705_planner_20261017',
      [ValidateSet('csim','synthesis','cosim','package','all')][string]$Stage='all')
$ErrorActionPreference='Stop'
$env:PROCESSOR_ARCHITECTURE='AMD64'
$root=Split-Path -Parent $PSScriptRoot
$src=Join-Path $BuildDirectory 'src'
$work=Join-Path $BuildDirectory 'hls'
New-Item -ItemType Directory -Force $src | Out-Null
Copy-Item -Path "$root\hls_source\tcb705\*.cpp","$root\hls_source\tcb705\*.h","$root\hls_source\tcb705\*.cfg","$root\hls_source\tcb705\vectors.txt" -Destination $src -Force
Copy-Item -LiteralPath "$root\native\tcb_planner\math7.hpp" -Destination $src -Force
Copy-Item -LiteralPath "$root\hls_source\tcb705\pl_math7.hpp" -Destination $src -Force
$run='D:\Xilinx\Vitis\2024.2\bin\vitis-run.bat'
$compile='D:\Xilinx\Vitis\2024.2\bin\v++.bat'
Push-Location $src
try {
    foreach($step in @('csim','synthesis','cosim','package')) {
        if($Stage -ne 'all' -and $Stage -ne $step){continue}
        Write-Output "Running $step with tcb_planner_2024.cfg in $work"
        if($step -eq 'synthesis') {
            & $compile -c --mode hls --config tcb_planner_2024.cfg --work_dir $work *> "$BuildDirectory\$step.log"
        }else{
            & $run --mode hls "--$step" --config tcb_planner_2024.cfg --work_dir $work *> "$BuildDirectory\$step.log"
        }
        if($LASTEXITCODE -ne 0){throw "$step failed: $BuildDirectory\$step.log"}
    }
}finally{Pop-Location}
