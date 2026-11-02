param([string]$HlsDirectory='C:\fpga_build\tcb705_planner_20261017_r4',
      [string]$VendorDirectory='',
      [string]$ProjectDirectory='',
      [string]$IpDirectory='',
      [switch]$GePl)
$ErrorActionPreference='Stop'
$env:PROCESSOR_ARCHITECTURE='AMD64'
$root=Split-Path -Parent $PSScriptRoot
if(!$ProjectDirectory){$ProjectDirectory=Join-Path $root 'hw\vivado'}
if(!$VendorDirectory){$VendorDirectory=Join-Path $root 'hw\vendor\md0700r'}
$tool='D:\Xilinx\Vivado\2024.2\bin\vivado.bat'
$ip=Join-Path $HlsDirectory 'hls\hls\impl\ip'
if(!(Test-Path -LiteralPath "$ip\component.xml")){throw 'Packaged seven-axis HLS IP is required'}
$cosim=Get-Content -LiteralPath "$HlsDirectory\cosim.log" -Raw
if($cosim -notmatch 'C/RTL co-simulation finished: PASS'){throw 'Seven-axis RTL co-simulation has not passed'}
# Store a local IP repository so the resulting project does not depend on an
# external temporary HLS directory. Only reuse an identical packaged core.
$localIp=if($IpDirectory){[IO.Path]::GetFullPath($IpDirectory)}else{Join-Path $root 'hw\ip\tcb7'}
if(Test-Path -LiteralPath $localIp){
    foreach($source in Get-ChildItem -LiteralPath $ip -Recurse -File){
        $relative=$source.FullName.Substring($ip.Length).TrimStart('\')
        $copy=Join-Path $localIp $relative
        if(!(Test-Path -LiteralPath $copy) -or (Get-FileHash -LiteralPath $source.FullName).Hash -ne (Get-FileHash -LiteralPath $copy).Hash){throw "Local IP differs: $relative; use a new repository directory"}
    }
}else{
    New-Item -ItemType Directory -Force (Split-Path -Parent $localIp) | Out-Null
    Copy-Item -LiteralPath $ip -Destination $localIp -Recurse
}
$ip=$localIp
if(Test-Path -LiteralPath "$ProjectDirectory\tcb705_md0700r.xpr"){throw 'Use a new project directory to preserve previous results'}
New-Item -ItemType Directory -Force $ProjectDirectory | Out-Null
$steps=@(
    @{Name='create';Script="$root\hw\md0700r\create_fused.tcl";Args=@($VendorDirectory,$ip,$ProjectDirectory,'planner')},
    @{Name='touch';Script="$root\hw\md0700r\gt911_pl\apply_gt911_pl.tcl";Args=@("$ProjectDirectory\tcb705_md0700r.xpr")},
    @{Name='clock';Script="$root\hw\md0700r\apply_tcb_clock.tcl";Args=@("$ProjectDirectory\tcb705_md0700r.xpr")}
)
if($GePl){$steps+=@{Name='ethernet';Script="$root\hw\ge_pl\apply_ge_pl.tcl";Args=@("$ProjectDirectory\tcb705_md0700r.xpr")}}
$steps+=@{Name='build';Script="$root\hw\md0700r\build_fused.tcl";Args=@("$ProjectDirectory\tcb705_md0700r.xpr")}
foreach($step in $steps){
    Write-Output "Vivado $($step.Name): $($step.Script)"
    & $tool -mode batch -nojournal -log "$ProjectDirectory\$($step.Name).log" -source $step.Script -tclargs @($step.Args) *> "$ProjectDirectory\$($step.Name).console.log"
    if($LASTEXITCODE -ne 0){throw "Vivado $($step.Name) failed; inspect $ProjectDirectory"}
}
Write-Output "VIVADO_BUILD_DONE: $ProjectDirectory\tcb705_md0700r.xpr"
