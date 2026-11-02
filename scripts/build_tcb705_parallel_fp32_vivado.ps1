param(
    [string]$HlsDirectory='C:\fpga_build\p32one1',
    [string]$ProjectDirectory='',
    [ValidateSet('create','build','all')][string]$Stage='all'
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
if(!$ProjectDirectory){$ProjectDirectory='C:\fpga_build\p32full_20261024'}
$ProjectDirectory=[IO.Path]::GetFullPath($ProjectDirectory)
$vivado='D:\Xilinx\Vivado\2024.2\bin\vivado.bat'
$env:PROCESSOR_ARCHITECTURE='AMD64'
$logs=Join-Path $ProjectDirectory 'build_logs'
New-Item -ItemType Directory -Force $logs | Out-Null
if($Stage -eq 'all' -or $Stage -eq 'create') {
    $package=Join-Path $HlsDirectory 'hls_controller_throughput\hls\impl\ip'
    if(!(Test-Path -LiteralPath "$package\component.xml")) {
        $package=Join-Path $HlsDirectory 'w\hls\impl\ip'
    }
    if(!(Test-Path -LiteralPath "$package\component.xml")){throw 'Run FP32 HLS package first'}
    # Archive the exact packaged IP with this project; a new project must be fresh.
    $ip=Join-Path $ProjectDirectory 'ip_repo\planner_fp32'
    if(Test-Path -LiteralPath $ip){throw 'Project IP directory already exists; use a fresh output directory'}
    New-Item -ItemType Directory -Force (Split-Path -Parent $ip) | Out-Null
    Copy-Item -LiteralPath $package -Destination $ip -Recurse
    & $vivado -mode batch -source "$root\hw\parallel\create_fp32.tcl" -log "$logs\create.log" -journal "$logs\create.jou" -tclargs $root $ip $ProjectDirectory *> "$logs\create_console.log"
    if($LASTEXITCODE -ne 0){throw "Vivado project creation failed: $logs\create_console.log"}
}
if($Stage -eq 'all' -or $Stage -eq 'build') {
    & $vivado -mode batch -source "$root\hw\parallel\build_fp32.tcl" -log "$logs\build.log" -journal "$logs\build.jou" -tclargs "$ProjectDirectory\tcb705_parallel_fp32.xpr" *> "$logs\build_console.log"
    if($LASTEXITCODE -ne 0){throw "Vivado build failed: $logs\build_console.log"}
}
Write-Output "FP32_VIVADO_$Stage COMPLETE: $ProjectDirectory"
Write-Output 'This command does not program the board or move the robot.'
