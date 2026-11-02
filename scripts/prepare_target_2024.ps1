#Requires -Version 5.1
param(
    [string]$BuildDir='C:\fpga_build\so101_target_2024_1003',
    [string]$Vitis='D:\Xilinx\Vitis\2024.2',
    [string]$Vivado='D:\Xilinx\Vivado\2024.2',
    [string]$Python='C:\Users\gongj\AppData\Local\Programs\Python\Python312\python.exe',
    [switch]$Cosim
)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskBuild=[IO.Path]::GetFullPath($BuildDir)
if ($taskBuild -match '[^\x00-\x7F]') {throw 'Use an ASCII build path for AMD tools'}
if (Test-Path -LiteralPath (Join-Path $taskBuild 'vivado\so101_target_ik.xpr')) {throw 'Project exists; open its .xpr or choose a new BuildDir'}
$env:PROCESSOR_ARCHITECTURE='AMD64'
foreach ($tool in @("$Vitis\bin\v++.bat","$Vitis\bin\vitis-run.bat","$Vivado\bin\vivado.bat",$Python)) {
    if (-not (Test-Path -LiteralPath $tool)) {throw "Missing tool: $tool"}
}
$taskSrc=Join-Path $taskBuild 'src'
$taskHls=Join-Path $taskBuild 'hls'
$taskExport=Join-Path $taskBuild 'export'
New-Item -ItemType Directory -Path $taskSrc,$taskExport -Force | Out-Null
& $Python "$taskRoot\scripts\generate_target_vectors.py" "$taskRoot\hls_source\target_vectors.txt"
if ($LASTEXITCODE -ne 0) {throw 'Vector generation failed'}
foreach ($name in @('ik_target.cpp','ik_target.h','ik_math.h','ik_step.h','ik_target_2024.cfg','tb_ik_target.cpp','target_vectors.txt')) {
    Copy-Item -LiteralPath "$taskRoot\hls_source\$name" -Destination $taskSrc
}
Copy-Item -LiteralPath "$taskRoot\hw\target_ik\create_project_2024.tcl","$taskRoot\hw\target_ik\ps7_board.tcl","$taskRoot\hw\target_ik\export_after_bitstream.tcl" -Destination $taskSrc
Push-Location $taskSrc
try {
    & "$Vitis\bin\vitis-run.bat" --mode hls --csim --config ik_target_2024.cfg --work_dir $taskHls
    if ($LASTEXITCODE -ne 0) {throw 'HLS C simulation failed'}
    & "$Vitis\bin\v++.bat" -c --mode hls --config ik_target_2024.cfg --work_dir $taskHls
    if ($LASTEXITCODE -ne 0) {throw 'HLS synthesis failed'}
    if ($Cosim) {
        & "$Vitis\bin\vitis-run.bat" --mode hls --cosim --config ik_target_2024.cfg --work_dir $taskHls
        if ($LASTEXITCODE -ne 0) {throw 'C/RTL co-simulation failed'}
    }
    & "$Vitis\bin\vitis-run.bat" --mode hls --package --config ik_target_2024.cfg --work_dir $taskHls
    if ($LASTEXITCODE -ne 0) {throw 'IP packaging failed'}
    $taskComponents=@(Get-ChildItem -LiteralPath $taskHls -Filter component.xml -Recurse | Where-Object { $_.DirectoryName -match '[\\/]impl[\\/]ip$' })
    if ($taskComponents.Count -ne 1) {throw 'Cannot identify packaged target IP'}
    $taskHeaders=@(Get-ChildItem -LiteralPath $taskHls -Filter xz20_ik_target_hw.h -Recurse | Where-Object { $_.FullName -match '[\\/]impl[\\/]ip[\\/]' })
    if ($taskHeaders.Count -ne 1) {throw 'Cannot identify generated register header'}
    & $Python "$taskRoot\scripts\export_target_register_map.py" $taskHeaders[0].FullName "$taskExport\drawing_target.registers.json"
    if ($LASTEXITCODE -ne 0) {throw 'Register export failed'}
    & "$Vivado\bin\vivado.bat" -mode batch -source create_project_2024.tcl -tclargs "$taskBuild\vivado" $taskComponents[0].DirectoryName
    if ($LASTEXITCODE -ne 0) {throw 'Vivado project creation failed'}
    if (-not (Test-Path -LiteralPath "$taskBuild\vivado\so101_target_ik.xpr")) {throw 'No .xpr generated'}
} finally {Pop-Location}
Write-Host "Open $taskBuild\vivado\so101_target_ik.xpr in Vivado 2024.2; run Generate Bitstream yourself."
