param([string]$BuildDirectory='C:\fpga_build\tcb705_lineart_20261020',
      [ValidateSet('csim','synthesis','cosim','package','all')][string]$Stage='all')
$ErrorActionPreference='Stop'
$env:PROCESSOR_ARCHITECTURE='AMD64'
$root=Split-Path -Parent $PSScriptRoot
$src=Join-Path $BuildDirectory 'src'
$work=Join-Path $BuildDirectory 'hls'
New-Item -ItemType Directory -Force $src | Out-Null
foreach($name in @('tcb_lineart_accel.cpp','tcb_lineart_accel.h','tb_lineart.cpp','lineart_2024.cfg')) {
    Copy-Item -LiteralPath "$root\hls_source\tcb705\$name" -Destination $src -Force
}
Push-Location $src
try {
    foreach($step in @('csim','synthesis','cosim','package')) {
        if($Stage -ne 'all' -and $Stage -ne $step){continue}
        if($step -eq 'csim' -or $step -eq 'cosim') {
            $vectorArgs=@("$root\tools\lineart_vectors.py", "$src\lineart_vectors.bin")
            if($step -eq 'cosim'){$vectorArgs+='--cosim'}
            & "$root\.venv\Scripts\python.exe" @vectorArgs
            if($LASTEXITCODE -ne 0){throw 'vector generation failed'}
            Copy-Item "$src\lineart_vectors.json" "$BuildDirectory\${step}_vectors.json" -Force
        }
        Write-Output "Running $step with lineart_2024.cfg in $work"
        if($step -eq 'synthesis') {
            & 'D:\Xilinx\Vitis\2024.2\bin\v++.bat' -c --mode hls --config lineart_2024.cfg --work_dir $work *> "$BuildDirectory\$step.log"
        }else{
            & 'D:\Xilinx\Vitis\2024.2\bin\vitis-run.bat' --mode hls "--$step" --config lineart_2024.cfg --work_dir $work *> "$BuildDirectory\$step.log"
        }
        if($LASTEXITCODE -ne 0){throw "$step failed: $BuildDirectory\$step.log"}
    }
}finally{Pop-Location}
