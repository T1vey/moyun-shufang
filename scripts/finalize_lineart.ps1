param([string]$HlsDirectory='C:\fpga_build\tcb705_lineart_20261020')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$python=Join-Path $root '.venv\Scripts\python.exe'
$export=Join-Path $root 'hw\vivado_lineart\export'
$platform=Join-Path $root 'overlay\tcb705_lineart'
$logs=Join-Path $root 'build\tcb705\lineart_build'
$dist=Join-Path $root 'dist'
$env:PYTHONIOENCODING='utf-8'
$env:PROCESSOR_ARCHITECTURE='AMD64'
if(!(Test-Path "$export\build_verified.json")){throw 'Verified Vivado export not present'}
foreach($name in @('tcb_lineart_accel.cpp','tcb_lineart_accel.h','tb_lineart.cpp','lineart_2024.cfg')) {
    if((Get-FileHash "$root\hls_source\tcb705\$name").Hash -ne (Get-FileHash "$HlsDirectory\src\$name").Hash){throw "HLS source changed since build: $name"}
}
$plannerHeaders=@(Get-ChildItem "$root\hw\ip\tcb7_v2c" -Recurse -Filter xtcb_planner_accel_hw.h)
if($plannerHeaders.Count -ne 1){throw 'Ambiguous planner register header'}
& $python "$root\scripts\package_tcb705_platform.py" --export $export --header $plannerHeaders[0].FullName --output $platform --build-id tcb705_lineart_20261020_r1 --ge-pl-dtbo "$root\overlay\tcb705_v2c_ge_pl\ge_pl.dtbo" --lineart-header "$root\hw\ip\lineart\drivers\tcb_lineart_accel_v1_0\src\xtcb_lineart_accel_hw.h"
if($LASTEXITCODE -ne 0){throw 'Platform sealing failed'}
& $python "$root\tools\summarize_lineart_build.py" --export $export
if($LASTEXITCODE -ne 0){throw 'Evidence validation failed'}
New-Item -ItemType Directory -Force $dist | Out-Null
$archive=Join-Path $dist 'TCB705_20261020_lineart_r1.zip'
& $python "$root\scripts\package_tcb705.py" $archive --platform $platform
if($LASTEXITCODE -ne 0){throw 'Source delivery packaging failed'}
$hardwareArchive=Join-Path $dist 'TCB705_lineart_20261020_fpga.zip'
& $python "$root\tools\package_lineart_hardware.py" $hardwareArchive
if($LASTEXITCODE -ne 0){throw 'Hardware delivery packaging failed'}
$vivadoArchive=Join-Path $dist 'TCB705_lineart_20261020_vivado.zip'
& 'D:\Xilinx\Vivado\2024.2\bin\vivado.bat' -mode batch -source "$root\hw\lineart\archive_lineart.tcl" -log "$logs\archive.log" -journal "$logs\archive.jou" -tclargs "$root\hw\vivado_lineart\tcb705_lineart.xpr" $vivadoArchive *> "$logs\archive_console.log"
if($LASTEXITCODE -ne 0){throw 'Vivado archive failed; inspect archive_console.log'}
foreach($path in @($archive,$hardwareArchive,$vivadoArchive)) {
    $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
    "$hash  $([IO.Path]::GetFileName($path))" | Set-Content -Encoding ascii ($path+'.sha256')
}
Write-Output 'LINEART_DELIVERY_COMPLETE_NO_BOARD_PROGRAMMING'
