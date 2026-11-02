param([string]$HlsDirectory='C:\fpga_build\brush_vision',
      [string]$ProjectDirectory='',
      [ValidateSet('create','build','all')][string]$Stage='all')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
if(!$ProjectDirectory){$ProjectDirectory=Join-Path $root 'hw\vivado_vision'}
$vivado='D:\Xilinx\Vivado\2024.2\bin\vivado.bat'
$env:PROCESSOR_ARCHITECTURE='AMD64'
$logs=Join-Path $root 'build\tcb705\vision_build'
New-Item -ItemType Directory -Force $logs | Out-Null
if($Stage -eq 'all' -or $Stage -eq 'create') {
    $ip=Join-Path $root 'hw\ip\vision'
    $package=Join-Path $HlsDirectory 'hls\hls\impl\ip'
    if(!(Test-Path "$package\component.xml")){throw 'Run the HLS package stage first'}
    if(Test-Path $ip){throw 'hw/ip/vision exists; archive it explicitly before installing a new package'}
    Copy-Item -LiteralPath $package -Destination $ip -Recurse
    & $vivado -mode batch -source "$root\hw\vision\create_vision.tcl" -log "$logs\create.log" -journal "$logs\create.jou" -tclargs $root $ip $ProjectDirectory *> "$logs\create_console.log"
    if($LASTEXITCODE -ne 0){throw "Vivado create failed: $logs\create_console.log"}
}
if($Stage -eq 'all' -or $Stage -eq 'build') {
    & $vivado -mode batch -source "$root\hw\md0700r\build_fused.tcl" -log "$logs\build.log" -journal "$logs\build.jou" -tclargs "$ProjectDirectory\tcb705_vision.xpr" *> "$logs\build_console.log"
    if($LASTEXITCODE -ne 0){throw "Vivado build failed: $logs\build_console.log"}
}
Write-Output "VISION_VIVADO_$Stage COMPLETE: $ProjectDirectory"
