param([string]$ProjectDirectory='C:\fpga_build\audio_fp32_20261027')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$vivado='D:\Xilinx\Vivado\2024.2\bin\vivado.bat'
$env:PROCESSOR_ARCHITECTURE='AMD64'
$ip=Join-Path $ProjectDirectory 'ip_repo\planner_fp32'
if(Test-Path -LiteralPath $ip){throw 'Choose a fresh build directory'}
New-Item -ItemType Directory -Force (Split-Path -Parent $ip) | Out-Null
Copy-Item -LiteralPath 'C:\fpga_build\p32one1\w\hls\impl\ip' -Destination $ip -Recurse
$logs=Join-Path $ProjectDirectory 'build_logs'
New-Item -ItemType Directory -Force $logs | Out-Null
& $vivado -mode batch -source "$root\hw\parallel\create_fp32.tcl" -log "$logs\create.log" -journal "$logs\create.jou" -tclargs $root $ip $ProjectDirectory audio *> "$logs\create_console.log"
if($LASTEXITCODE -ne 0){throw "Create failed: $logs\create_console.log"}
& $vivado -mode batch -source "$root\hw\parallel\build_fp32.tcl" -log "$logs\build.log" -journal "$logs\build.jou" -tclargs "$ProjectDirectory\tcb705_parallel_fp32.xpr" *> "$logs\build_console.log"
if($LASTEXITCODE -ne 0){throw "Build failed: $logs\build_console.log"}
Write-Output "AUDIO_FP32_BUILD_COMPLETE $ProjectDirectory\export"
